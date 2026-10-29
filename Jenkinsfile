// CI/CD via the shared Jenkins library (github.com/yesuvadian/jenkins-pipeline-lib).
//   dev  branch → 192.168.0.109           (automatic)
//   main branch → 192.168.0.105 + DR .100 (after approval in Jenkins)
// Secrets (DB/SMTP/keys…) come from Jenkins secret-file credentials
// customer-api-dev-env / customer-api-prod-env — never from this repo.
@Library('cogniwatt-lib') _

// Same overrides deploy/docker-compose.yml forces on top of .env
def common = [
    REDIS_HOST:            'host.docker.internal',
    LICENSE_SERVER_URL:    'http://host.docker.internal:8001',
    LICENSE_SERVER_UI_URL: 'http://host.docker.internal:3001',
    APP_NAME:              'Relu-Vendor-API',
    ENABLE_SCHEDULER:      'true',
    PORT:                  '8000',
]

cogniwattPipeline(
    app:           'customer-api',
    dockerfile:    'Dockerfile',
    containerPort: 8000,
    hostPort:      8001,   // 8000 is taken by the bare-metal customer-api service
    healthPath:    '/docs',
    secretEnv:     true,
    volumes:       ['./uploads:/app/uploads'],   // keep uploaded files across deploys
    replaces:      ['deploy-api-1'],   // old deploy-docker.ps1 container on 8001 — stopped on first Jenkins deploy
    env: [
        dev:  common + [DB_HOST: 'host.docker.internal', DB_PORT: '5432', BASE_URL: 'https://devsupplier.cogniwatt.com'],
        prod: common + [DB_HOST: '192.168.0.162',        DB_PORT: '6432', BASE_URL: 'https://api.procurement.cogniwatt.com'],
    ],
    // DR shares the production database — only the primary may run the
    // in-process APScheduler, or every scheduled job would fire twice.
    drEnv: [ENABLE_SCHEDULER: 'false'],

    // Run both deployments side by side until the Docker one takes over:
    //   docker → container on :8001       legacy → systemd service on :8000 (was deploy.ps1)
    // Drop 'legacy' (or 'docker') from a list to switch that deployment off.
    deployModes: [dev: ['docker', 'legacy'], prod: ['docker', 'legacy']],
    legacy: [
        from:   '/app',                          // same code the container runs
        keep:   ['.env', 'venv', 'uploads'],     // server-owned; never overwritten
        delete: false,                           // overlay, like deploy.ps1's tar -x
        health: 'curl -sf -o /dev/null http://localhost:8000/docs',
        dev:  [path: '/apps/customer/api', commands: [
            'venv/bin/pip install -q --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt',
            'sudo -n /usr/bin/systemctl restart customer-api',
        ]],
        // pip install on prod too: deploy.ps1 never did, which left DR's venv
        // without `cryptography` and its API crash-looping (found 2026-10-14).
        prod: [path: '/apps/customer/api', commands: [
            'venv/bin/pip install -q --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt',
            'sudo -n /usr/bin/systemctl restart api-procurement',
        ]],
    ],
)
