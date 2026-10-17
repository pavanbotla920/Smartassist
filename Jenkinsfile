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

        stage('Docker Build') {
            steps {
                sh 'docker build -t smartassist-kisan:jenkins-test .'
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
