from django.test import SimpleTestCase
import chat.routing
import re


class TestWebsocketRouting(SimpleTestCase):
    def test_ws_route_matches_conversation_id(self):
        patterns = chat.routing.websocket_urlpatterns
        test_path = '/ws/chat/1/'
        candidates = [test_path, test_path.lstrip('/'), test_path.strip('/')]
        matched = False
        for p in patterns:
            # pattern.pattern is a RoutePattern; try to access compiled regex
            try:
                regex = p.pattern.regex
            except Exception:
                regex = None
            if regex is not None:
                for candidate in candidates:
                    if regex.match(candidate):
                        matched = True
                        break
                if matched:
                    break
            else:
                # Fallback: try string route
                try:
                    route = p.pattern._route
                    for candidate in candidates:
                        if re.match(route, candidate):
                            matched = True
                            break
                    if matched:
                        break
                        matched = True
                        break
                except Exception:
                    continue

        self.assertTrue(matched, msg=f"No websocket pattern matched {test_path}")
