"""Opt-in physical locking tests for an explicitly isolated MariaDB database."""

from __future__ import annotations

import ipaddress
import os
import queue
import threading
import time
import unittest
from uuid import uuid4

import MySQLdb

from tareas.models import CorrelativoEmpresa, Tarea
from tareas.services.task_mutation_locks import (
    TaskMutationConflict,
    bounded_mysql_lock_wait,
    lock_mysql_task_rows,
)


_REQUIRED_ENV = (
    "TAREAS_MARIADB_TEST_HOST",
    "TAREAS_MARIADB_TEST_PORT",
    "TAREAS_MARIADB_TEST_DATABASE",
    "TAREAS_MARIADB_TEST_USER",
    "TAREAS_MARIADB_TEST_PASSWORD",
    "TAREAS_MARIADB_TEST_INSTANCE_ID",
)


def _quote_identifier(value: str) -> str:
    return f"`{value.replace('`', '``')}`"


@unittest.skipUnless(
    os.environ.get("TAREAS_MARIADB_TEST_HOST"),
    "requires an explicitly configured isolated local MariaDB test database",
)
class MariaDBMutationLockIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
        if missing:
            raise AssertionError(
                "Incomplete isolated MariaDB test configuration: "
                + ", ".join(missing)
            )

        host = os.environ["TAREAS_MARIADB_TEST_HOST"]
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise AssertionError(
                "The test server must be addressed by a loopback IP."
            ) from exc
        if not address.is_loopback:
            raise AssertionError(
                "The test server must be local; remote databases are forbidden."
            )

        database = os.environ["TAREAS_MARIADB_TEST_DATABASE"]
        username = os.environ["TAREAS_MARIADB_TEST_USER"]
        if not database.startswith("tareas_it_") or database == "tareas":
            raise AssertionError(
                "The test database must use the dedicated tareas_it_ prefix."
            )
        if not username.startswith("tareas_it_"):
            raise AssertionError(
                "Use a dedicated non-business tareas_it_ test user."
            )

        cls.config = {
            "host": host,
            "port": int(os.environ["TAREAS_MARIADB_TEST_PORT"]),
            "user": username,
            "passwd": os.environ["TAREAS_MARIADB_TEST_PASSWORD"],
            "db": database,
            "connect_timeout": 5,
            "charset": "utf8mb4",
        }
        cls.task_table = Tarea._meta.db_table
        cls.sequence_table = CorrelativoEmpresa._meta.db_table
        cls.created_tables = []
        cls.connection = MySQLdb.connect(**cls.config, autocommit=True)
        try:
            cls._verify_isolation(cls.connection)
            cls._create_test_tables()
        except BaseException:
            cls._drop_created_tables()
            cls.connection.close()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            cls._verify_isolation(cls.connection)
            cls._drop_created_tables()
        finally:
            cls.connection.close()
            super().tearDownClass()

    @classmethod
    def _verify_isolation(cls, connection):
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT VERSION(), @@hostname, @@port, DATABASE(), "
                "CURRENT_USER(), @@server_id, @@global.read_only, "
                "@@session.autocommit, @@session.tx_isolation"
            )
            row = cursor.fetchone()
            if row is None:
                raise AssertionError("MariaDB identity query returned no result.")
            (
                version,
                _hostname,
                port,
                database,
                current_user,
                _server_id,
                read_only,
                autocommit,
                isolation,
            ) = row
            if "mariadb" not in str(version).casefold():
                raise AssertionError(
                    "Physical concurrency tests require MariaDB."
                )
            if int(port) != cls.config["port"] or database != cls.config["db"]:
                raise AssertionError(
                    "The server-selected port or database differs from configuration."
                )
            if not str(current_user).split("@", 1)[0].startswith("tareas_it_"):
                raise AssertionError("The connected database user is not isolated.")
            if bool(read_only):
                raise AssertionError("The isolated test database is read-only.")
            if int(autocommit) != 1:
                raise AssertionError(
                    "The identity connection must start in autocommit mode."
                )
            if str(isolation).upper() not in {
                "READ-UNCOMMITTED",
                "READ-COMMITTED",
                "REPEATABLE-READ",
                "SERIALIZABLE",
            }:
                raise AssertionError(
                    "The server returned an unrecognized transaction isolation."
                )

            cursor.execute(
                "SELECT `marker` FROM `tareas_it_isolation_marker` WHERE `id` = 1"
            )
            marker = cursor.fetchone()
            if (
                marker is None
                or marker[0] != os.environ["TAREAS_MARIADB_TEST_INSTANCE_ID"]
            ):
                raise AssertionError(
                    "The explicit database isolation marker did not match."
                )
            cursor.execute(
                "SELECT `table_name` FROM `information_schema`.`tables` "
                "WHERE `table_schema` = %s",
                (cls.config["db"],),
            )
            tables = {table[0] for table in cursor.fetchall()}
            allowed = {"tareas_it_isolation_marker"}
            allowed.update(cls.created_tables)
            if not tables.issubset(allowed):
                raise AssertionError(
                    "The isolated database contains unexpected tables."
                )
        finally:
            cursor.close()

    @classmethod
    def _create_test_tables(cls):
        task = _quote_identifier(cls.task_table)
        sequence = _quote_identifier(cls.sequence_table)
        cursor = cls.connection.cursor()
        try:
            cursor.execute(
                f"CREATE TABLE {sequence} ("
                "`empresa_id` BIGINT UNSIGNED NOT NULL PRIMARY KEY, "
                "`siguiente_numero` INT UNSIGNED NOT NULL"
                ") ENGINE=InnoDB"
            )
            cls.created_tables.append(cls.sequence_table)
            cursor.execute(
                f"CREATE TABLE {task} ("
                "`id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, "
                "`empresa_id` BIGINT UNSIGNED NOT NULL, "
                "INDEX `tareas_it_empresa_idx` (`empresa_id`)"
                ") ENGINE=InnoDB"
            )
            cls.created_tables.append(cls.task_table)
            cursor.execute(
                "SELECT `table_name`, `engine` FROM `information_schema`.`tables` "
                "WHERE `table_schema` = %s AND `table_name` IN (%s, %s)",
                (cls.config["db"], cls.task_table, cls.sequence_table),
            )
            engines = {table: engine for table, engine in cursor.fetchall()}
            if set(engines) != {cls.task_table, cls.sequence_table} or any(
                str(engine).casefold() != "innodb"
                for engine in engines.values()
            ):
                raise AssertionError(
                    "The synthetic lock tables must both be InnoDB."
                )
        finally:
            cursor.close()

    @classmethod
    def _drop_created_tables(cls):
        if not cls.created_tables:
            return
        cls._verify_identity_only(cls.connection)
        cursor = cls.connection.cursor()
        try:
            for table_name in reversed(cls.created_tables):
                cursor.execute(f"DROP TABLE {_quote_identifier(table_name)}")
        finally:
            cursor.close()
            cls.created_tables.clear()

    @classmethod
    def _verify_identity_only(cls, connection):
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT DATABASE(), CURRENT_USER()"
            )
            row = cursor.fetchone()
            if (
                row is None
                or row[0] != cls.config["db"]
                or not str(row[1]).split("@", 1)[0].startswith("tareas_it_")
            ):
                raise AssertionError(
                    "Refusing cleanup because the database identity changed."
                )
            cursor.execute(
                "SELECT `marker` FROM `tareas_it_isolation_marker` WHERE `id` = 1"
            )
            marker = cursor.fetchone()
            if (
                marker is None
                or marker[0] != os.environ["TAREAS_MARIADB_TEST_INSTANCE_ID"]
            ):
                raise AssertionError(
                    "Refusing cleanup because the isolation marker changed."
                )
        finally:
            cursor.close()

    def _connect(self):
        return MySQLdb.connect(**self.config, autocommit=False)

    @staticmethod
    def _new_company_id():
        return 1_000_000_000 + uuid4().int % 8_000_000_000

    def _insert_task(self, company_id):
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                f"INSERT INTO {_quote_identifier(self.task_table)} (`empresa_id`) "
                "VALUES (%s)",
                (company_id,),
            )
            task_id = cursor.lastrowid
        finally:
            cursor.close()
        return task_id

    def test_company_without_tasks_gets_a_transactional_sentinel(self):
        company_id = self._new_company_id()
        connection = self._connect()
        try:
            connection.begin()
            lock_mysql_task_rows(connection, company_id, ())
            connection.rollback()

            cursor = connection.cursor()
            try:
                cursor.execute(
                    f"SELECT COUNT(*) FROM {_quote_identifier(self.sequence_table)} "
                    "WHERE `empresa_id` = %s",
                    (company_id,),
                )
                self.assertEqual(cursor.fetchone()[0], 0)
            finally:
                cursor.close()
        finally:
            connection.close()

    def test_same_company_mutations_serialize_across_connections(self):
        company_id = self._new_company_id()
        task_id = self._insert_task(company_id)
        first_connection = self._connect()
        second_connection = self._connect()
        first_has_lock = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()
        second_finished = threading.Event()
        errors = queue.Queue()

        def hold_lock():
            try:
                first_connection.begin()
                with bounded_mysql_lock_wait(first_connection):
                    lock_mysql_task_rows(
                        first_connection,
                        company_id,
                        (task_id,),
                    )
                    first_has_lock.set()
                    if not release_first.wait(timeout=10):
                        raise AssertionError("Timed out waiting to release the test lock.")
                    first_connection.commit()
            except BaseException as exc:
                errors.put(exc)
                release_first.set()

        def wait_for_lock():
            try:
                second_connection.begin()
                second_started.set()
                with bounded_mysql_lock_wait(second_connection):
                    lock_mysql_task_rows(
                        second_connection,
                        company_id,
                        (task_id,),
                    )
                    second_connection.commit()
            except BaseException as exc:
                errors.put(exc)
            finally:
                second_finished.set()

        first_thread = threading.Thread(target=hold_lock, daemon=True)
        second_thread = threading.Thread(target=wait_for_lock, daemon=True)
        try:
            first_thread.start()
            self.assertTrue(first_has_lock.wait(timeout=5))
            second_thread.start()
            self.assertTrue(second_started.wait(timeout=5))
            time.sleep(0.25)
            self.assertFalse(second_finished.is_set())
            release_first.set()
            self.assertTrue(second_finished.wait(timeout=10))
            first_thread.join(timeout=2)
            second_thread.join(timeout=2)
            self.assertTrue(errors.empty(), "A mutation lock worker failed.")
        finally:
            release_first.set()
            first_connection.close()
            second_connection.close()

    def test_lock_timeout_is_reported_as_a_controlled_conflict(self):
        company_id = self._new_company_id()
        first_connection = self._connect()
        second_connection = self._connect()
        first_connection.begin()
        second_connection.begin()
        try:
            lock_mysql_task_rows(first_connection, company_id, ())
            with self.assertRaises(TaskMutationConflict):
                with bounded_mysql_lock_wait(second_connection):
                    lock_mysql_task_rows(second_connection, company_id, ())
        finally:
            first_connection.rollback()
            second_connection.rollback()
            first_connection.close()
            second_connection.close()
