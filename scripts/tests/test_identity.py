"""Contrato estructural de identidad; no inicia servicios ni solicita tokens."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = ROOT / "identity" / "keycloak"


def load_realm(name):
    return json.loads((IDENTITY / name).read_text(encoding="utf-8"))


class LegacyIdentityTests(unittest.TestCase):
    def test_legacy_realm_roles_and_clients_remain_compatible(self):
        realm = load_realm("realm-config.example.json")
        self.assertEqual(realm["realm"], "odontoclinic-realm")
        self.assertEqual({r["name"] for r in realm["roles"]["realm"]}, {
            "ROLE_ADMIN", "ROLE_DENTISTA", "ROLE_ASISTENTE",
            "ROLE_RECEPCIONISTA", "ROLE_PACIENTE",
        })
        clients = {c["clientId"]: c for c in realm["clients"]}
        self.assertEqual(set(clients), {
            "web-portal-frontend", "ms1-seguridad-service",
            "ms2-expediente-service", "ms3-agendamiento-service",
        })
        portal = clients["web-portal-frontend"]
        self.assertTrue(portal["publicClient"])
        self.assertTrue(portal["standardFlowEnabled"])
        self.assertTrue(portal["directAccessGrantsEnabled"])
        self.assertFalse(portal["implicitFlowEnabled"])
        self.assertEqual(portal["redirectUris"], [
            "http://localhost/*", "http://localhost:3000/*",
        ])
        self.assertEqual(portal["webOrigins"], ["+"])
        for name in set(clients) - {"web-portal-frontend"}:
            self.assertTrue(clients[name]["enabled"])
            self.assertTrue(clients[name]["bearerOnly"])


class ErpIdentityTests(unittest.TestCase):
    def setUp(self):
        self.realm = load_realm("dental-platform-realm.example.json")

    def test_separate_realm_uses_raw_backend_roles(self):
        self.assertEqual(self.realm["realm"], "dental-platform")
        self.assertTrue(self.realm["enabled"])
        self.assertFalse(self.realm["registrationAllowed"])
        roles = [r["name"] for r in self.realm["roles"]["realm"]]
        self.assertEqual(len(roles), 4)
        self.assertEqual(set(roles), {"ADMIN", "RECEPCIONISTA", "CAJERO", "ODONTOLOGO"})

    def test_frontend_requires_code_pkce_and_explicit_origin(self):
        self.assertEqual(len(self.realm["clients"]), 1)
        client = self.realm["clients"][0]
        self.assertEqual(client["clientId"], "mf-erp")
        self.assertTrue(client["enabled"])
        self.assertEqual(client["protocol"], "openid-connect")
        self.assertTrue(client["publicClient"])
        self.assertTrue(client["standardFlowEnabled"])
        for flag in ("implicitFlowEnabled", "directAccessGrantsEnabled",
                     "serviceAccountsEnabled", "bearerOnly"):
            self.assertFalse(client[flag], flag)
        self.assertEqual(client["attributes"]["pkce.code.challenge.method"], "S256")
        self.assertEqual(client["redirectUris"], ["http://localhost:4201/*"])
        self.assertEqual(client["webOrigins"], ["http://localhost:4201"])
        self.assertEqual(client["attributes"]["post.logout.redirect.uris"],
                         "http://localhost:4201/*")

    def test_roles_and_audience_are_in_access_tokens(self):
        client = self.realm["clients"][0]
        self.assertIn("profile", client["defaultClientScopes"])
        self.assertIn("roles", client["defaultClientScopes"])
        mappers = client["protocolMappers"]
        audience = [m for m in mappers if m["protocolMapper"] == "oidc-audience-mapper"]
        self.assertEqual(len(audience), 1)
        self.assertEqual(audience[0]["protocol"], "openid-connect")
        self.assertEqual(audience[0]["config"], {
            "included.custom.audience": "ms-erp",
            "id.token.claim": "false",
            "access.token.claim": "true",
        })

    def test_examples_have_no_users_or_credentials(self):
        def inspect(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    self.assertNotIn(key.lower(), {
                        "users", "credentials", "password", "secret", "clientsecret",
                    })
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)
        inspect(self.realm)
        inspect(load_realm("realm-config.example.json"))

    def test_documentation_names_supported_modes_and_limitations(self):
        text = (IDENTITY / "README.md").read_text(encoding="utf-8")
        for required in (
            "dental-platform-realm.example.json", "odontoclinic-realm",
            "KEYCLOAK_ISSUER_URI", "ERP_LOCAL_JWT_ISSUER_URI", "ERP_PORT=8081",
            "realm_access.roles", "preferred_username", "ROLE_ROLE_ADMIN",
            "http://localhost:8180/realms/dental-platform", "127.0.0.1",
            "discovery", "JWKS", "X-Dev-User", "no valida la audiencia",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
