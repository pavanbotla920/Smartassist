# 🌾 SmartAssist: AI-Powered Government Scheme Platform

SmartAssist is a comprehensive, AI-driven web application designed to bridge the digital divide between citizens and government welfare schemes. Built specifically with farmers in mind, it provides personalized scheme recommendations, multilingual voice assistance, and a streamlined application tracking system.

## ✨ Key Features

*   **🤖 AI-Powered Recommendations:** Matches users to eligible government schemes based on their age, income, category, and location using a custom weighted scoring algorithm.
*   **🗺️ Interactive India Map:** Explore and filter central and state-specific schemes dynamically using an interactive map interface.
*   **🌐 Multilingual & Voice-Enabled:** Full translation support (English, Hindi, Marathi, Telugu) with text-to-speech audio for scheme details.
*   **📊 Personalized Dashboard:** Track application statuses, view recent alerts, and monitor profile completeness.
*   **👥 Volunteer & Admin Workflow:** Allows admins to manage schemes, track user applications, and update statuses (which triggers automatic email notifications).
*   **🔒 Secure Profiles:** Detailed user profiles with dynamic state/district dropdowns, photo uploads, and password validation.

## 🛠️ Technology Stack

*   **Backend:** Django 6.0 (Python)
*   **Database:** SQLite (Default), easily upgradable to PostgreSQL
*   **Frontend:** HTML5, CSS3 (Custom Green/Cream/Gold Theme), Vanilla JavaScript, Bootstrap 5
*   **Data Visualization:** Chart.js
*   **Mapping:** Leaflet.js & GeoJSON
*   **Voice/Audio:** Edge-TTS (Text-to-Speech) and Web Speech API (Speech-to-Text)
*   **AI/Translation:** OpenAI API (Optional) & MyMemory Translation API

## 🚀 Getting Started

Follow these steps to run the project locally on your machine.

### 1. Prerequisites
*   Python 3.10 or higher installed.
*   Git installed.

### 2. Clone the Repository
```bash
git clone https://github.com/pavanbotla920/Smartassist-main.git
cd Smartassist-main
```

### 3. Set Up Virtual Environment
It is highly recommended to use a virtual environment:
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Database Setup
Apply the Django migrations to set up the SQLite database:
```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Load Initial Scheme Data (Optional)
If you have a `schemes.csv` file, you can load it into the database using the custom script:
```bash
python manage.py shell
# Inside the shell:
from farmers.load_data import run
run()
exit()
```

### 7. Create an Admin Account
To access the Django Admin panel and manage schemes:
```bash
python manage.py createsuperuser
```
*(Follow the prompts to set a username, email, and password).*

### 8. Run the Server
```bash
python manage.py runserver
```
Open your browser and navigate to `http://127.0.0.1:8000/`.

---

## ⚙️ Configuration (Optional Features)

### Gmail Email Notifications
To enable automatic emails when an application status changes, you need a Gmail App Password.
1. Go to your Google Account -> Security -> 2-Step Verification -> App Passwords.
2. Generate a new password for "Mail".
3. Set these environment variables in your terminal before running the server:
```bash
export EMAIL_HOST_USER="yourgmail@gmail.com"
export EMAIL_HOST_PASSWORD="xxxx xxxx xxxx xxxx"
```

### OpenAI Chatbot Integration
If you have an OpenAI API key and want the chatbot to use GPT-4o-mini, export your key:
```bash
export OPENAI_API_KEY="sk-..."
```

---

## 📂 Project Structure

```text
Smartassist-main/
│
├── farmers/                 # Main Django app
│   ├── migrations/          # Database migrations
│   ├── forms.py             # Custom forms and validation logic
│   ├── models.py            # Database models (UserProfile, Scheme, Notification)
│   ├── views.py             # Core business logic & API endpoints
│   ├── location_data.py     # Helper for State/District JSON mapping
│   └── load_data.py         # Script to import CSV data
│
├── smartassist/             # Project configuration
│   ├── settings.py          # Django settings (Email, i18n, Apps)
│   └── urls.py              # Main URL routing
│
├── static/                  # Static assets
│   ├── css/                 # styles.css (Green/Cream theme), scheme-platform.css
│   ├── js/                  # Chatbot, voice assistants, map logic
│   └── india_states.geojson # Map data
│
├── templates/               # HTML files
│   ├── base.html            # Master template (Navbar, Footer)
│   ├── dashboard.html       # User dashboard
│   ├── profile.html         # Detailed farmer profile
│   ├── recommend.html       # AI Scheme matching form
│   └── scheme_awareness.html# Main scheme directory with map & filters
│
├── states_districts.csv     # Data for dynamic location dropdowns
├── requirements.txt         # Python dependencies
└── manage.py                # Django entry point
```

## 🤝 Contributing
Contributions are welcome! If you'd like to improve the UI, add more AI matching logic, or fix bugs:
1. Fork the repository.
2. Create a new branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

## 📄 License
This project is open-source and available under the MIT License.
