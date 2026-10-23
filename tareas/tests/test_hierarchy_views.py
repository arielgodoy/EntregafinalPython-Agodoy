from datetime import date
import re

"""Pruebas focalizadas de navegación jerárquica en modo lectura."""

from django.db import connection
from django.test import Client, TestCase
from django.urls import reverse
from django.test.utils import CaptureQueriesContext

from organizacion.models import Departamento, OrganizationalSource
from tareas.models import Tarea, TareaConnectionRole, TareaRelacion
from tareas.services.detail_storage import DjangoTaskDetailStorage, TaskDetailSections
from tareas.services.hierarchy import add_child
from tareas.services.lifecycle import annul_task, transition_task
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class HierarchyViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="00", descripcion="Empresa navegación")
        cls.otra_empresa = create_empresa(codigo="02", descripcion="Empresa externa")
        cls.user = create_user(username="hierarchy_view_user")
        assign_permission(cls.user, cls.empresa, "Tareas", ingresar=True)
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS", source_type="DJANGO", django_alias="default"
        )

    def setUp(self):
        self.client.login(username="hierarchy_view_user", password="password-prueba")
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def make_task(self, title, empresa=None):
        return create_tarea(
            empresa or self.empresa,
            self.user,
            titulo=title,
            responsable=self.user,
            fecha_tope=date.today(),
        )

    def make_active_task(self, title, empresa=None):
        task = self.make_task(title, empresa)
        task.publicar(self.user)
        return task

    def grant_create(self, user=None):
        assign_permission(
            user or self.user,
            self.empresa,
            "Tareas",
            ingresar=True,
            crear=True,
        )

    def get_detail(self, task):
        return self.client.get(reverse("tareas:detalle_tarea", args=[task.pk]))

    def assert_task_link(self, response, task):
        url = reverse("tareas:detalle_tarea", args=[task.pk])
        pattern = (
            rf'<a\b[^>]*href="{re.escape(url)}"[^>]*>\s*'
            rf'{re.escape(task.correlativo)}\s*-\s*{re.escape(task.titulo)}\s*</a>'
        )
        self.assertRegex(response.content.decode(), pattern)

    def test_detalle_raiz_muestra_hijas_con_correlativo(self):
        parent = self.make_task("Padre raíz")
        child = self.make_task("Hija directa")
        add_child(parent, child)

        response = self.get_detail(parent)

        self.assertContains(response, 'data-key="tareas.hierarchy.kind.mother"')
        self.assertContains(response, "Hija directa")
        self.assertContains(response, child.correlativo)
        self.assert_task_link(response, child)

    def test_detalle_hija_muestra_padre(self):
        parent = self.make_task("Padre visible")
        child = self.make_task("Hija visible")
        add_child(parent, child)

        response = self.get_detail(child)

        self.assertContains(response, 'data-key="tareas.hierarchy.kind.child"')
        self.assertContains(response, 'data-key="tareas.hierarchy.parent"')
        self.assertContains(response, "Padre visible")
        self.assertContains(response, parent.correlativo)
        self.assertNotContains(
            response,
            'data-key="tareas.hierarchy.children"',
        )
        self.assert_task_link(response, parent)

    def test_detalle_hija_muestra_sus_nietas(self):
        parent = self.make_task("Padre")
        child = self.make_task("Hija")
        grandchild = self.make_task("Nieta")
        add_child(parent, child)
        add_child(child, grandchild)

        response = self.get_detail(child)

        self.assertContains(response, 'data-key="tareas.hierarchy.kind.child"')
        self.assertContains(response, 'data-key="tareas.hierarchy.kind.also_mother"')
        self.assertContains(response, "Nieta")
        self.assertContains(response, grandchild.correlativo)
        self.assert_task_link(response, parent)
        self.assert_task_link(response, grandchild)

    def test_enlaces_apuntan_al_detalle_correcto(self):
        parent = self.make_task("Padre enlazado")
        child = self.make_task("Hija enlazada")
        add_child(parent, child)

        response = self.get_detail(child)

        self.assertContains(response, reverse("tareas:detalle_tarea", args=[parent.pk]))

    def test_navegacion_padre_hija_nieta(self):
        parent = self.make_task("Nivel padre")
        child = self.make_task("Nivel hija")
        grandchild = self.make_task("Nivel nieta")
        add_child(parent, child)
        add_child(child, grandchild)

        root_response = self.get_detail(parent)
        child_response = self.client.get(
            reverse("tareas:detalle_tarea", args=[child.pk])
        )
        grandchild_response = self.client.get(
            reverse("tareas:detalle_tarea", args=[grandchild.pk])
        )

        self.assertContains(root_response, reverse("tareas:detalle_tarea", args=[child.pk]))
        self.assertContains(child_response, reverse("tareas:detalle_tarea", args=[grandchild.pk]))
        self.assertContains(grandchild_response, reverse("tareas:detalle_tarea", args=[child.pk]))
        self.assertContains(grandchild_response, reverse("tareas:detalle_tarea", args=[parent.pk]))
        self.assertContains(
            grandchild_response,
            'data-key="tareas.hierarchy.kind.grandchild"',
        )
        self.assertContains(
            grandchild_response,
            'data-key="tareas.hierarchy.direct_mother"',
        )
        self.assertContains(
            grandchild_response,
            'data-key="tareas.hierarchy.kind.main"',
        )
        self.assertNotContains(
            grandchild_response,
            'data-key="tareas.hierarchy.children"',
        )
        self.assert_task_link(root_response, child)
        self.assert_task_link(child_response, parent)
        self.assert_task_link(child_response, grandchild)
        self.assert_task_link(grandchild_response, child)
        self.assert_task_link(grandchild_response, parent)

    def test_jerarquia_vacia_no_rompe_detalle(self):
        response = self.get_detail(self.make_task("Sin jerarquía"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sin jerarquía")
        self.assertContains(
            response,
            'data-key="tareas.hierarchy.kind.main"',
        )
        self.assertNotContains(response, 'id="tareas-jerarquia-titulo"')

    def test_tarea_anulada_directamente_se_representa(self):
        task = self.make_task("Tarea anulada")
        task.publicar(self.user)
        transition_task(task, Tarea.Estado.GESTION, self.user, "INICIAR_GESTION")
        annul_task(task, self.user)

        response = self.get_detail(task)

        self.assertContains(response, "Anulada")

    def test_hija_anulada_efectivamente_por_padre_se_representa(self):
        parent = self.make_task("Padre anulado")
        child = self.make_task("Hija afectada")
        parent.publicar(self.user)
        child.publicar(self.user)
        transition_task(parent, Tarea.Estado.GESTION, self.user, "INICIAR_GESTION")
        transition_task(child, Tarea.Estado.GESTION, self.user, "INICIAR_GESTION")
        add_child(parent, child)
        annul_task(parent, self.user)

        response = self.get_detail(child)

        self.assertContains(response, "Anulada por tarea superior")

    def test_aislamiento_multiempresa_en_navegacion(self):
        task = self.make_task("Tarea de empresa activa")
        external = self.make_task("Tarea de otra empresa", empresa=self.otra_empresa)

        response = self.get_detail(task)
        external_response = self.client.get(
            reverse("tareas:detalle_tarea", args=[external.pk])
        )

        self.assertNotContains(response, "Tarea de otra empresa")
        self.assertEqual(external_response.status_code, 404)

    def test_related_tasks_from_other_companies_are_not_rendered(self):
        task = self.make_task("Tarea de empresa activa")
        foreign_parent = self.make_task(
            "Madre de otra empresa",
            empresa=self.otra_empresa,
        )
        foreign_child = self.make_task(
            "Hija de otra empresa",
            empresa=self.otra_empresa,
        )
        TareaRelacion.objects.create(padre=foreign_parent, hija=task)
        TareaRelacion.objects.create(padre=task, hija=foreign_child)

        response = self.get_detail(task)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, foreign_parent.titulo)
        self.assertNotContains(response, foreign_child.titulo)
        self.assertNotContains(
            response,
            f'href="{reverse("tareas:detalle_tarea", args=[foreign_parent.pk])}"',
        )
        self.assertNotContains(
            response,
            f'href="{reverse("tareas:detalle_tarea", args=[foreign_child.pk])}"',
        )

    def test_related_detail_links_do_not_bypass_ingresar_permission(self):
        parent = self.make_task("Madre con permiso")
        child = self.make_task("Hija protegida")
        add_child(parent, child)
        self.assert_task_link(self.get_detail(parent), child)

        reader = create_user("hierarchy-related-link-reader")
        client = Client()
        client.force_login(reader)
        session = client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

        response = client.get(
            reverse("tareas:detalle_tarea", args=[child.pk])
        )

        self.assertEqual(response.status_code, 403)

    def test_detail_get_does_not_write_task_or_hierarchy_rows(self):
        parent = self.make_task("Madre de solo lectura")
        child = self.make_task("Hija de solo lectura")
        add_child(parent, child)
        before = (Tarea.objects.count(), TareaRelacion.objects.count())

        response = self.get_detail(parent)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (Tarea.objects.count(), TareaRelacion.objects.count()),
            before,
        )

    def test_detail_hierarchy_reads_children_without_n_plus_one_queries(self):
        parent = self.make_task("Madre con varias hijas")
        storage = DjangoTaskDetailStorage("default")
        sections = TaskDetailSections(
            mini_tasks=False,
            links=False,
            milestones=False,
            documents=False,
        )
        with CaptureQueriesContext(connection) as without_children:
            storage.get_task_detail(
                task_id=parent.pk,
                empresa_id=self.empresa.pk,
                sections=sections,
            )

        for index in range(4):
            add_child(parent, self.make_task(f"Hija {index}"))

        with CaptureQueriesContext(connection) as with_children:
            result = storage.get_task_detail(
                task_id=parent.pk,
                empresa_id=self.empresa.pk,
                sections=sections,
            )

        self.assertEqual(len(result.hierarchy.children), 4)
        self.assertEqual(len(with_children), len(without_children))

    def test_hierarchy_classification_uses_relations_not_task_titles(self):
        main = self.make_task("Tarea nieta")
        child = self.make_task("Tarea principal")
        grandchild = self.make_task("Tarea madre")
        add_child(main, child)
        add_child(child, grandchild)

        main_response = self.get_detail(main)
        child_response = self.get_detail(child)
        grandchild_response = self.get_detail(grandchild)

        self.assertContains(
            main_response,
            'data-key="tareas.hierarchy.kind.mother"',
        )
        self.assertContains(
            child_response,
            'data-key="tareas.hierarchy.kind.child"',
        )
        self.assertContains(
            child_response,
            'data-key="tareas.hierarchy.kind.also_mother"',
        )
        self.assertContains(
            grandchild_response,
            'data-key="tareas.hierarchy.kind.grandchild"',
        )

    def test_hierarchy_badge_preserves_existing_detail_actions(self):
        assign_permission(
            self.user,
            self.empresa,
            "Tareas",
            ingresar=True,
            crear=True,
            modificar=True,
        )
        task = self.make_active_task("Detalle con acciones existentes")
        child = self.make_task("Hija del detalle existente")
        add_child(task, child)

        response = self.get_detail(task)

        self.assertContains(response, "task-detail__task-actions")
        self.assertContains(response, "badge bg-secondary-subtle text-secondary")
        self.assertContains(response, "link-primary text-decoration-underline")
        self.assertContains(response, 'data-key="tareas.actions.editar"')
        self.assertContains(response, 'data-key="tareas.reprogramming.action"')
        self.assertContains(response, 'data-key="tareas.actions.gestionar"')
        self.assertContains(response, 'data-key="tareas.actions.anular"')

    def test_no_aparecen_acciones_de_reparenting(self):
        response = self.get_detail(self.make_task("Solo lectura"))

        self.assertNotContains(response, "reparent")
        self.assertNotContains(response, "crear relación")

    def test_create_child_action_is_limited_by_state_depth_and_create_permission(self):
        assign_permission(
            self.user,
            self.empresa,
            "Tareas",
            ingresar=True,
            crear=True,
        )
        root = self.make_active_task("Madre raíz")
        child = self.make_active_task("Hija activa")
        add_child(root, child)
        grandchild = self.make_active_task("Nieta activa")
        add_child(child, grandchild)

        for task, expected in (
            (root, True),
            (child, True),
            (grandchild, False),
            (self.make_task("Madre borrador"), False),
        ):
            with self.subTest(task=task.titulo):
                response = self.get_detail(task)
                self.assertEqual(
                    response.context["puede_crear_tarea_hija"],
                    expected,
                )
                target = (
                    f"{reverse('tareas:crear_tarea')}?tarea_madre={task.pk}"
                )
                if expected:
                    self.assertContains(response, target)
                else:
                    self.assertNotContains(response, target)

        reader = create_user("hierarchy-no-create-reader")
        assign_permission(
            reader,
            self.empresa,
            "Tareas",
            ingresar=True,
        )
        reader_client = Client()
        reader_client.force_login(reader)
        session = reader_client.session
        session["empresa_id"] = self.empresa.pk
        session.save()
        reader_response = reader_client.get(
            reverse("tareas:detalle_tarea", args=[root.pk])
        )
        self.assertFalse(
            reader_response.context["puede_crear_tarea_hija"]
        )
        self.assertNotContains(
            reader_response,
            f"{reverse('tareas:crear_tarea')}?tarea_madre={root.pk}",
        )

    def test_create_child_form_preselects_parent_and_posts_full_draft_task(self):
        assign_permission(
            self.user,
            self.empresa,
            "Tareas",
            ingresar=True,
            crear=True,
        )
        parent = self.make_active_task("A0000013 — tarea madre 1")
        create_url = reverse("tareas:crear_tarea")
        query_url = f"{create_url}?tarea_madre={parent.pk}"

        preview = self.client.get(query_url)

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(
            preview.context["form"].selected_parent.task_id,
            parent.pk,
        )
        self.assertContains(preview, parent.correlativo)
        self.assertContains(
            preview,
            "tareas.hierarchy.form.type_child",
        )

        response = self.client.post(
            create_url,
            {
                "titulo": "Hija completa de tarea madre",
                "descripcion": "Detalle de la hija",
                "prioridad": Tarea.Prioridad.URGENTE,
                "responsable": self.user.pk,
                "fecha_tope": date.today().isoformat(),
                "tarea_madre": parent.pk,
            },
        )

        child = Tarea.objects.get(titulo="Hija completa de tarea madre")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("tareas:detalle_tarea", args=[child.pk]),
        )
        self.assertEqual(child.estado, Tarea.Estado.BORRADOR)
        self.assertTrue(child.correlativo.startswith("B"))
        self.assertEqual(child.empresa_id, self.empresa.pk)
        self.assertEqual(child.prioridad, Tarea.Prioridad.URGENTE)
        self.assertEqual(child.responsable_id, self.user.pk)
        self.assertEqual(child.fecha_tope, date.today())
        self.assertTrue(
            TareaRelacion.objects.filter(
                padre_id=parent.pk,
                hija_id=child.pk,
            ).exists()
        )

    def test_department_parent_prefills_and_allows_same_company_override(self):
        assign_permission(
            self.user,
            self.empresa,
            "Tareas",
            ingresar=True,
            crear=True,
        )
        parent_department = Departamento.objects.create(
            empresa=self.empresa,
            codigo="HIER-DEP-A",
            nombre="Departamento madre",
            source=OrganizationalSource.LOCAL,
        )
        child_department = Departamento.objects.create(
            empresa=self.empresa,
            codigo="HIER-DEP-B",
            nombre="Departamento hija",
            source=OrganizationalSource.LOCAL,
        )
        parent = self.make_task("Madre por departamento")
        parent.tipo_ambito = Tarea.Ambito.DEPARTAMENTO
        parent.departamento = parent_department
        parent.save(update_fields=["tipo_ambito", "departamento"])
        parent.publicar(self.user)

        create_url = reverse("tareas:crear_tarea")
        preview = self.client.get(f"{create_url}?tarea_madre={parent.pk}")

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(
            preview.context["form"]["departamento"].value(),
            parent_department.pk,
        )
        self.assertContains(
            preview,
            "tareas.hierarchy.form.type_child",
        )

        response = self.client.post(
            create_url,
            {
                "titulo": "Hija en otro departamento",
                "prioridad": Tarea.Prioridad.NORMAL,
                "responsable": self.user.pk,
                "fecha_tope": date.today().isoformat(),
                "tarea_madre": parent.pk,
                "departamento": child_department.pk,
            },
        )

        child = Tarea.objects.get(titulo="Hija en otro departamento")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(child.tipo_ambito, Tarea.Ambito.DEPARTAMENTO)
        self.assertEqual(child.departamento_id, child_department.pk)
        self.assertIsNone(child.local_id)

    def test_staff_and_superuser_without_create_do_not_get_hierarchy_action(self):
        parent = self.make_active_task("Madre sin permiso C")
        for attribute in ("is_staff", "is_superuser"):
            with self.subTest(attribute=attribute):
                user = create_user(f"hierarchy-no-create-{attribute}")
                setattr(user, attribute, True)
                user.save(update_fields=[attribute])
                assign_permission(
                    user,
                    self.empresa,
                    "Tareas",
                    ingresar=True,
                )
                client = Client()
                client.force_login(user)
                session = client.session
                session["empresa_id"] = self.empresa.pk
                session.save()

                detail = client.get(
                    reverse("tareas:detalle_tarea", args=[parent.pk])
                )
                self.assertFalse(
                    detail.context["puede_crear_tarea_hija"]
                )
                response = client.post(
                    reverse("tareas:crear_tarea"),
                    {
                        "titulo": "Hija no autorizada",
                        "fecha_tope": date.today().isoformat(),
                        "tarea_madre": parent.pk,
                    },
                )
                self.assertEqual(response.status_code, 403)
                self.assertFalse(
                    Tarea.objects.filter(titulo="Hija no autorizada").exists()
                )

    def test_active_root_and_child_offer_the_same_create_form_but_grandchild_does_not(self):
        self.grant_create()
        root = self.make_active_task("Madre raíz")
        child = self.make_active_task("Hija activa")
        add_child(root, child)
        grandchild = self.make_active_task("Nieta activa")
        add_child(child, grandchild)

        for task, should_offer in (
            (root, True),
            (child, True),
            (grandchild, False),
        ):
            with self.subTest(task=task.titulo):
                response = self.get_detail(task)
                self.assertEqual(
                    response.context["puede_crear_tarea_hija"],
                    should_offer,
                )
                if should_offer:
                    self.assertContains(
                        response,
                        f"{reverse('tareas:crear_tarea')}?tarea_madre={task.pk}",
                    )
                else:
                    self.assertNotContains(
                        response,
                        f"{reverse('tareas:crear_tarea')}?tarea_madre={task.pk}",
                    )

        preselected = self.client.get(
            f"{reverse('tareas:crear_tarea')}?tarea_madre={child.pk}"
        )
        self.assertEqual(preselected.status_code, 200)
        self.assertEqual(preselected.context["form"].selected_parent.task_id, child.pk)
        self.assertContains(preselected, child.correlativo)
        self.assertContains(
            preselected,
            "tareas.hierarchy.form.type_grandchild",
        )

    def test_create_form_post_creates_child_draft_and_relation(self):
        self.grant_create()
        parent = self.make_active_task("Madre para alta")
        response = self.client.post(
            reverse("tareas:crear_tarea"),
            {
                "titulo": "Tarea hija completa",
                "descripcion": "Descripción",
                "prioridad": Tarea.Prioridad.URGENTE,
                "responsable": self.user.pk,
                "fecha_tope": date.today().isoformat(),
                "tarea_madre": parent.pk,
            },
        )

        child = Tarea.objects.get(titulo="Tarea hija completa")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("tareas:detalle_tarea", args=[child.pk]),
        )
        self.assertEqual(child.estado, Tarea.Estado.BORRADOR)
        self.assertTrue(child.correlativo.startswith("B"))
        self.assertEqual(child.empresa_id, self.empresa.pk)
        self.assertEqual(child.prioridad, Tarea.Prioridad.URGENTE)
        self.assertEqual(child.responsable_id, self.user.pk)
        self.assertEqual(child.fecha_tope, date.today())
        self.assertTrue(
            TareaRelacion.objects.filter(
                padre_id=parent.pk,
                hija_id=child.pk,
            ).exists()
        )

    def test_create_action_requires_create_permission_for_staff_and_superuser(self):
        parent = self.make_active_task("Madre con lector")
        for attribute in ("is_staff", "is_superuser"):
            with self.subTest(attribute=attribute):
                user = create_user(f"hierarchy-no-create-{attribute}")
                setattr(user, attribute, True)
                user.save(update_fields=[attribute])
                assign_permission(user, self.empresa, "Tareas", ingresar=True)
                client = Client()
                client.force_login(user)
                session = client.session
                session["empresa_id"] = self.empresa.pk
                session.save()

                detail = client.get(
                    reverse("tareas:detalle_tarea", args=[parent.pk])
                )
                self.assertEqual(detail.status_code, 200)
                self.assertFalse(
                    detail.context["puede_crear_tarea_hija"]
                )
                post = client.post(
                    reverse("tareas:crear_tarea"),
                    {
                        "titulo": "No autorizada",
                        "fecha_tope": date.today().isoformat(),
                        "tarea_madre": parent.pk,
                    },
                )
                self.assertEqual(post.status_code, 403)
                self.assertFalse(Tarea.objects.filter(titulo="No autorizada").exists())
