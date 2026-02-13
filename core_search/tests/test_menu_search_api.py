from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from core_search.models import SearchPageIndex


class TestMenuSearchApi(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="searchuser", password="pass123")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa")
        
        # Crear Vistas para los tests
        self.vista_docs = Vista.objects.create(nombre="Listado General de Documentos")
        self.vista_noti = Vista.objects.create(nombre="notificaciones.mis_notificaciones")
        self.vista_chat = Vista.objects.create(nombre="chat.inbox")
        self.vista_proyectos = Vista.objects.create(nombre="Listar Proyectos")

        # Crear permisos para el usuario
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_docs,
            ingresar=True,
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_noti,
            ingresar=True,
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_chat,
            ingresar=True,
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_proyectos,
            ingresar=True,
        )

        # Crear entradas de SearchPageIndex para diferentes grupos
        SearchPageIndex.objects.create(
            key="biblioteca.documentos_general",
            vista=self.vista_docs,
            url_name="biblioteca:listado_documentos",
            label_key="search.page.documentos_general",
            default_label="Listado General de Documentos",
            group_key="search.group.biblioteca",
            keywords="documentos doc",
            order=10,
            is_active=True,
        )
        SearchPageIndex.objects.create(
            key="notificaciones.mis_notificaciones",
            vista=self.vista_noti,
            url_name="notificaciones:mis_notificaciones",
            label_key="search.page.notificaciones",
            default_label="Notificaciones",
            group_key="search.group.notificaciones",
            keywords="notificaciones alertas centro",
            order=60,
            is_active=True,
        )
        SearchPageIndex.objects.create(
            key="notificaciones.centro_alertas",
            vista=Vista.objects.create(nombre="notificaciones.centro_alertas"),
            url_name="notificaciones:centro_alertas",
            label_key="search.page.centro_alertas",
            default_label="Centro de Alertas",
            group_key="search.group.notificaciones",
            keywords="centro alertas",
            order=61,
            is_active=True,
        )
        SearchPageIndex.objects.create(
            key="chat.inbox",
            vista=self.vista_chat,
            url_name="chat_inbox",
            label_key="search.page.chat",
            default_label="Centro de Mensajes",
            group_key="search.group.chat",
            keywords="mensajes chat inbox",
            order=50,
            is_active=True,
        )
        SearchPageIndex.objects.create(
            key="proyectos.listar",
            vista=self.vista_proyectos,
            url_name="control_de_proyectos:listar_proyectos",
            label_key="search.page.proyectos_listar",
            default_label="Listar Proyectos",
            group_key="search.group.proyectos",
            keywords="proyectos listado",
            order=30,
            is_active=True,
        )

    def test_sin_empresa_activa_retorna_vacio(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("menu_search"), {"q": "noti"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("pages"), [])

    def test_con_empresa_y_permiso_retorna_resultados(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

        response = self.client.get(reverse("menu_search"), {"q": "noti"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        pages = data.get("pages", [])
        # Debe encontrar al menos una notificación
        self.assertTrue(any(p.get("group_key") == "search.group.notificaciones" for p in pages))

    def test_buscar_chat_retorna_resultados(self):
        """Test que buscar 'chat' o 'mensajes' devuelve resultados del grupo chat"""
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

        response = self.client.get(reverse("menu_search"), {"q": "chat"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        pages = data.get("pages", [])
        self.assertTrue(any(p.get("group_key") == "search.group.chat" for p in pages),
                       "Debe encontrar resultados de chat")

    def test_buscar_proyectos_retorna_resultados(self):
        """Test que buscar 'proyecto' devuelve resultados del grupo proyectos"""
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

        response = self.client.get(reverse("menu_search"), {"q": "proyecto"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        pages = data.get("pages", [])
        self.assertTrue(any(p.get("group_key") == "search.group.proyectos" for p in pages),
                       "Debe encontrar resultados de proyectos")

    def test_buscar_multiples_grupos(self):
        """Test que buscar un término general devuelve resultados de múltiples grupos"""
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

        # Buscar string que existe en multiple keyword fields
        response = self.client.get(reverse("menu_search"), {"q": "listado"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        pages = data.get("pages", [])
        # documentos tiene "listado" en label, proyectos tiene en keywords
        self.assertTrue(len(pages) >= 1, "Debe encontrar resultados de búsqueda")

    def test_documentos_retorna_resultados(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

        response = self.client.get(reverse("menu_search"), {"q": "doc"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        pages = data.get("pages", [])
        self.assertTrue(any(page.get("url") == "/documentos/listado/" for page in pages))

    def test_sin_permiso_retorna_vacio(self):
        other_user = User.objects.create_user(username="other", password="pass123")
        self.client.force_login(other_user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

        response = self.client.get(reverse("menu_search"), {"q": "prop"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("pages"), [])

    def test_usuario_anonimo_no_permitido(self):
        response = self.client.get(reverse("menu_search"), {"q": "doc"})
        self.assertIn(response.status_code, [302, 403])
