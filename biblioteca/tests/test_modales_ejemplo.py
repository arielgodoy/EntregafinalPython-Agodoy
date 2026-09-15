from django.test import SimpleTestCase
from django.urls import NoReverseMatch, reverse


class ModalesEjemploEndpointTests(SimpleTestCase):
    def test_demo_endpoint_is_not_exposed_in_productive_urls(self):
        with self.assertRaises(NoReverseMatch):
            reverse("biblioteca:modales_ejemplo")
