"""Static checks for the Azure-to-GCP clinical gateway."""
import json
import re
import unittest
from pathlib import Path

from test_deploy_config import locations

ROOT = Path(__file__).resolve().parents[2]


class GcpArtifactsTest(unittest.TestCase):
    def test_compose_and_inactive_workflow(self):
        text = (ROOT / 'deploy/gcp/compose.yml').read_text()
        for value in ('network_mode: host', 'quay.io/keycloak/keycloak:26.8.1',
                      'start --import-realm', 'docker.n8n.io/n8nio/n8n:2.47.2',
                      '127.0.0.1:8081:8080', '127.0.0.1:5678:5678',
                      'N8N_SECURE_COOKIE: "true"', 'N8N_ENCRYPTION_KEY:',
                      'WEBHOOK_URL: https://n8n.35-237-1-132.sslip.io/'):
            self.assertIn(value, text)
        self.assertNotIn('start-dev', text)
        self.assertNotIn('ports:', text.split('  keycloak-db:')[1].split('  keycloak:')[0])
        workflow = json.loads((ROOT / 'automation/n8n/workflows/n8n-workflow-multicanal.json').read_text())
        self.assertFalse(workflow['active'])
        self.assertIn('import:workflow', text)
        self.assertIn('.multicanal-imported', text)
        for service, binding in (('keycloak', '127.0.0.1:8081:8080'), ('n8n', '127.0.0.1:5678:5678')):
            block = re.split(r'\n  [a-z][a-z0-9-]*:\n', text.split('  ' + service + ':\n', 1)[1], maxsplit=1)[0]
            ports = re.findall(r'^      - "([^\"]+)"', block, re.M)
            self.assertEqual(ports, [binding])
        self.assertNotIn('6443:', text)

    def test_realm_contract(self):
        realm = json.loads((ROOT / 'identity/keycloak/dental-erp-realm.json').read_text())
        self.assertEqual(realm['realm'], 'dental-erp')
        self.assertNotIn('users', realm)
        self.assertEqual({r['name'] for r in realm['roles']['realm']},
                         {'ADMIN', 'ODONTOLOGO', 'RECEPCIONISTA', 'CAJERO', 'PACIENTE'})
        clients = {c['clientId']: c for c in realm['clients']}
        for client in clients.values():
            self.assertTrue(client['publicClient'])
            self.assertEqual(client['attributes']['pkce.code.challenge.method'], 'S256')
            self.assertNotIn('*', ''.join(client['redirectUris'] + client['webOrigins']))
        self.assertEqual(clients['mf-erp']['redirectUris'], ['https://20-83-242-208.sslip.io/auth/callback'])
        self.assertEqual(clients['dental-mobile']['redirectUris'], ['dentalmobile://auth'])
        audiences = {m['config']['included.custom.audience'] for m in clients['mf-erp']['protocolMappers']}
        self.assertEqual(audiences, {'ms-erp', 'ms2-clinico-ia', 'ms3-agenda-stock'})

    def test_k3s_edge_and_issuer(self):
        manifests = '\n'.join(p.read_text() for p in (ROOT / 'k8s').glob('*.yml'))
        caddy = (ROOT / 'deploy/gcp/Caddyfile').read_text()
        for value in ('kind: StatefulSet', 'image: mongo:7.0', 'clusterIP: None',
                      '--replSet', 'pacienteId: 1, fechaInferencia: -1',
                      'odontologoId: 1, estado: 1', 'livenessProbe:', 'readinessProbe:',
                      'imagePullPolicy: Never', 'minReplicas: 1', 'maxReplicas: 3',
                      'averageUtilization: 70'):
            self.assertIn(value, manifests)
        for ip in re.findall(r'clusterIP: (10\.43\.\d+\.\d+)', manifests):
            self.assertIn(ip, caddy)
        self.assertEqual(len(re.findall(r'clusterIP: 10\.43\.\d+\.\d+', manifests)), 2)
        self.assertNotIn('NodePort', manifests)
        self.assertIn('remote_ip 20.83.242.208', caddy)
        self.assertIn('respond 403', caddy)
        self.assertIn('25MB', caddy)
        self.assertEqual(manifests.count('minReplicas: 1'), 2)
        self.assertEqual(manifests.count('maxReplicas: 3'), 2)
        self.assertEqual(manifests.count('averageUtilization: 70'), 2)
        for probe in ('/api/expediente/health', '/api/expediente/health/ready', '/health'):
            self.assertIn(probe, manifests)
        self.assertEqual(manifests.count('livenessProbe:'), 2)
        self.assertEqual(manifests.count('readinessProbe:'), 2)
        self.assertNotIn('hostPort:', manifests)
        issuer = 'https://auth.35-237-1-132.sslip.io/realms/dental-erp'
        files = [ROOT / 'deploy/README.md', ROOT / 'deploy/azure/env.template',
                 ROOT / 'deploy/aws/env.template', ROOT / 'k8s/ms2-env.secret.template']
        found = set()
        for path in files:
            found.update(re.findall(r'https://auth\.35-237-1-132\.sslip\.io/realms/[a-z0-9-]+', path.read_text()))
        self.assertEqual(found, {issuer})


class GcpGatewayTest(unittest.TestCase):
    def test_clinical_proxy_preserves_security_and_routing(self):
        text = (ROOT / 'deploy/azure/gateway.conf.template').read_text(encoding='utf-8')
        body = locations(text)['/api/expediente/']
        for directive in (
            'if ($erp_preflight_denied) { return 403; }',
            'if ($erp_preflight_ok) { return 204; }',
            'client_max_body_size 25M;',
            'proxy_set_header Host 35-237-1-132.sslip.io;',
            'proxy_set_header X-Dev-User "";',
            'proxy_ssl_server_name on;',
            'proxy_ssl_name 35-237-1-132.sslip.io;',
            'proxy_ssl_verify on;',
            'proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;',
            'proxy_pass $gcp_edge;',
        ):
            self.assertIn(directive, body)
        self.assertIn('set $gcp_edge https://35-237-1-132.sslip.io;', text)
        self.assertNotIn('return 503', body)
