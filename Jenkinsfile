pipeline {
    agent any

    options {
        skipDefaultCheckout(true)
        timestamps()
    }

    parameters {
        booleanParam(
            name: 'BUILD_DOCKER_IMAGE',
            defaultValue: false,
            description: 'Build and publish the Docker image after CI and Selenium checks.'
        )
    }

    environment {
        CI_VENV = '.venv-ci'
        DJANGO_DB_PATH = '.ci-db.sqlite3'
        APP_PORT_FILE = '.ci-app-port'
        APP_PID_FILE = '.ci-server.pid'
        APP_LOG_FILE = '.ci-server.log'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                echo 'Preparing SmartAssist-Kisan source code'
                sh 'pwd'
                sh 'ls -la'
            }
        }

        stage('Python Environment') {
            steps {
                sh '''
                    set -eu
                    command -v python3
                    python3 - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit(
        f"Python 3.12+ is required; found {sys.version.split()[0]}"
    )
print(f"Using Python {sys.version.split()[0]}")
PY
                    python3 -m venv "$CI_VENV"
                    "$CI_VENV/bin/python" -m pip install --upgrade pip
                    "$CI_VENV/bin/python" -m pip install -r requirements.txt
                '''
            }
        }

        stage('Django System Check') {
            steps {
                sh '"$CI_VENV/bin/python" manage.py check'
            }
        }

        stage('Django Migration Check') {
            steps {
                sh '"$CI_VENV/bin/python" manage.py makemigrations --check --dry-run'
            }
        }

        stage('Production Settings Validation') {
            steps {
                sh '''
                    set -eu
                    set +x
                    ci_secret="$("$CI_VENV/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
                    DJANGO_ENV=production \
                    DJANGO_SETTINGS_MODULE=smartassist.settings \
                    DJANGO_SECRET_KEY="$ci_secret" \
                    DJANGO_ALLOWED_HOSTS=127.0.0.1 \
                    DJANGO_CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8003 \
                    DJANGO_CACHE_URL=redis://127.0.0.1:6379/0 \
                    DJANGO_DEBUG=False \
                        "$CI_VENV/bin/python" -c \
                        'import django; django.setup(); from django.conf import settings; assert settings.SECRET_KEY; assert settings.DEBUG is False'
                    unset ci_secret
                    set -x

                    if negative_output="$(env -u DJANGO_SECRET_KEY DJANGO_ENV=production \
                        DJANGO_SETTINGS_MODULE=smartassist.settings \
                        DJANGO_ALLOWED_HOSTS=127.0.0.1 \
                        DJANGO_CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8003 \
                        DJANGO_CACHE_URL=redis://127.0.0.1:6379/0 \
                        DJANGO_DEBUG=False \
                        "$CI_VENV/bin/python" -c 'import smartassist.settings' 2>&1)"; then
                        echo 'Production settings accepted a missing DJANGO_SECRET_KEY.'
                        exit 1
                    elif ! printf '%s' "$negative_output" | grep -Fq \
                        'ImproperlyConfigured: DJANGO_SECRET_KEY must be configured in production.'; then
                        echo 'Production settings failed for an unexpected reason during the missing-secret test.'
                        exit 1
                    fi
                '''
            }
        }

        stage('Django Tests') {
            steps {
                sh '"$CI_VENV/bin/python" manage.py test'
            }
        }

        stage('Start Application') {
            steps {
                sh '''
                    set -eu
                    rm -f "$APP_PORT_FILE" "$APP_PID_FILE"
                    APP_PORT="$("$CI_VENV/bin/python" -c \
                        'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
                    printf '%s\n' "$APP_PORT" > "$APP_PORT_FILE"
                    "$CI_VENV/bin/python" manage.py migrate --noinput
                    nohup "$CI_VENV/bin/python" manage.py runserver --noreload "0.0.0.0:$APP_PORT" \
                        > "$APP_LOG_FILE" 2>&1 &
                    echo $! > "$APP_PID_FILE"
                '''
            }
        }

        stage('Selenium UI Testing') {
            steps {
                sh '''
                    set -eu
                    if [ ! -s "$APP_PORT_FILE" ]; then
                        echo "Application port file is missing."
                        exit 1
                    fi
                    APP_PORT="$(cat "$APP_PORT_FILE")"
                    url="http://127.0.0.1:$APP_PORT/"
                    ready=false
                    for attempt in $(seq 1 60); do
                        if curl --fail --silent --show-error "$url" -o /dev/null; then
                            ready=true
                            break
                        fi
                        sleep 1
                    done
                    if [ "$ready" != true ]; then
                        echo "Application did not become ready at $url"
                        cat "$APP_LOG_FILE"
                        exit 1
                    fi

                    if command -v firefox >/dev/null 2>&1; then
                        browser=firefox
                    elif command -v google-chrome >/dev/null 2>&1; then
                        browser=chrome
                    elif command -v chromium >/dev/null 2>&1; then
                        browser=chromium
                    elif command -v chromium-browser >/dev/null 2>&1; then
                        browser=chromium
                    else
                        echo "No supported browser found (Firefox, Chrome, or Chromium)."
                        exit 1
                    fi

                    echo "Using browser: $browser"
                    BROWSER="$browser" BASE_URL="$url" \
                        "$CI_VENV/bin/python" -m unittest selenium_tests.test_homepage -v
                '''
            }
        }
        stage('Docker Build and Hub Push') {
            when {
                expression { params.BUILD_DOCKER_IMAGE }
            }
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'dockerhub-credentials',
                        usernameVariable: 'DOCKERHUB_USERNAME',
                        passwordVariable: 'DOCKERHUB_TOKEN'
                    )
                ]) {
                    sh '''
                        set +x
                        set -eu

                        trap 'docker logout >/dev/null 2>&1 || true' EXIT

                        IMAGE="pavanbotla/smartassist-kisan"

                        docker build \
                            -t "$IMAGE:1.0.1" \
                            -t "$IMAGE:latest" .

                        echo "$DOCKERHUB_TOKEN" | docker login \
                            --username "$DOCKERHUB_USERNAME" \
                            --password-stdin

                        docker push "$IMAGE:1.0.1"
                        docker push "$IMAGE:latest"
                    '''
                }
            }
        }
    }

    post {
        always {
            sh '''
                if [ -f "$APP_PID_FILE" ]; then
                    pid="$(cat "$APP_PID_FILE")"
                    if [ -f "$APP_PORT_FILE" ]; then
                        port="$(cat "$APP_PORT_FILE")"
                        command="$(ps -p "$pid" -o args= 2>/dev/null || true)"
                        case "$command" in
                            *"manage.py runserver --noreload 0.0.0.0:$port"*)
                                kill "$pid" || true
                                ;;
                        esac
                    fi
                    rm -f "$APP_PID_FILE"
                fi
                rm -f "$APP_LOG_FILE"
                rm -f "$APP_PORT_FILE"
                rm -f "$DJANGO_DB_PATH" "$DJANGO_DB_PATH"-journal "$DJANGO_DB_PATH"-wal "$DJANGO_DB_PATH"-shm
            '''
            echo 'SmartAssist-Kisan CI/CD pipeline finished.'
        }

        success {
            echo 'SUCCESS: SmartAssist-Kisan pipeline completed!'
        }

        failure {
            echo 'FAILURE: Check the Jenkins Console Output for details.'
        }
    }
}
