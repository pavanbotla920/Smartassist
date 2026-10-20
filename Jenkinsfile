pipeline {
    agent any

    stages {
        stage('Checkout') {
            steps {
                echo 'Preparing SmartAssist-Kisan source code'
                sh 'pwd'
                sh 'ls -la'
            }
        }

        stage('Python Environment') {
            steps {
                sh 'python3 --version'
                sh 'python3 -m venv .venv-ci'
                sh '.venv-ci/bin/python -m pip install --upgrade pip'
                sh '.venv-ci/bin/python -m pip install -r requirements.txt'
            }
        }

        stage('Django System Check') {
            steps {
                sh '.venv-ci/bin/python manage.py check'
            }
        }

        stage('Django Tests') {
            steps {
                sh '.venv-ci/bin/python manage.py test'
            }
        }

        stage('Selenium UI Testing') {
            steps {
                sh '''
                    echo "Checking SmartAssist-Kisan application..."
                    curl --fail --silent --show-error http://localhost:8003/ -o /dev/null

                    echo "Checking Firefox..."
                    /snap/firefox/current/usr/lib/firefox/firefox --version

                    echo "Checking GeckoDriver..."
                    /snap/firefox/current/usr/lib/firefox/geckodriver --version

                    echo "Running Selenium homepage test..."
                    .venv-ci/bin/python -m unittest selenium_tests.test_homepage -v
                '''
            }
        }

        stage('Docker Build') {
            steps {
                sh '''
                    docker build \
                        -t pavanbotla/smartassist-kisan:latest \
                        -t pavanbotla/smartassist-kisan:1.0.1 \
                        .
                '''
            }
        }

        stage('Docker Hub Push') {
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

                        echo "$DOCKERHUB_TOKEN" | docker login \
                            --username "$DOCKERHUB_USERNAME" \
                            --password-stdin

                        docker push pavanbotla/smartassist-kisan:1.0.1
                        docker push pavanbotla/smartassist-kisan:latest

                        docker logout
                    '''
                }
            }
        }
    }

    post {
        success {
            echo 'SUCCESS: SmartAssist-Kisan pipeline completed!'
        }

        failure {
            echo 'FAILURE: Check the Jenkins Console Output for details.'
        }

        always {
            echo 'SmartAssist-Kisan CI/CD pipeline finished.'
        }
    }
}