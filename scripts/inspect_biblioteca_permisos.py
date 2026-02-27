import sqlite3
from pathlib import Path
DB = Path(__file__).resolve().parents[1] / 'db.sqlite3'
conn = sqlite3.connect(str(DB))
cur = conn.cursor()
print('DB:', DB)
print('--- VISTAS que contienen Biblioteca ---')
cur.execute("SELECT id,nombre FROM access_control_vista WHERE nombre LIKE '%Biblioteca%'")
print(cur.fetchall())
print('\n--- PERMISOS (vistas cuyo nombre contiene Biblioteca) ---')
cur.execute("SELECT p.id,p.usuario_id,p.empresa_id,v.nombre,p.ingresar,p.crear,p.modificar,p.supervisor FROM access_control_permiso p JOIN access_control_vista v ON p.vista_id=v.id WHERE v.nombre LIKE '%Biblioteca%'")
print(cur.fetchall())
print('\n--- PERMISOS (muestra primeros 200) ---')
cur.execute("SELECT p.id,p.usuario_id,p.empresa_id,v.nombre,p.ingresar,p.supervisor FROM access_control_permiso p JOIN access_control_vista v ON p.vista_id=v.id LIMIT 200")
print(cur.fetchall())
conn.close()
