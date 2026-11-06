"""Small, deterministic translations available without network access."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalTranslation:
    text: str | None
    available: bool


_CATALOG = {
    "hi": {
        "home": "होम",
        "schemes": "योजनाएं",
        "dashboard": "डैशबोर्ड",
        "login": "लॉग इन",
        "logout": "लॉग आउट",
        "apply now": "अभी आवेदन करें",
        "official website": "आधिकारिक वेबसाइट",
        "search": "खोजें",
        "submit": "जमा करें",
        "cancel": "रद्द करें",
        "save": "सहेजें",
        "notifications": "सूचनाएं",
        "listen": "सुनें",
        "listen in": "इस भाषा में सुनें",
        "select voice language": "आवाज़ की भाषा चुनें",
        "pm kisan samman nidhi": "पीएम किसान सम्मान निधि",
        "eligibility": "पात्रता",
        "documents": "दस्तावेज़",
        "benefits": "लाभ",
        "all farmers": "सभी किसान",
        "eligible farmers": "पात्र किसान",
        "aadhaar card": "आधार कार्ड",
        "land records": "भूमि रिकॉर्ड",
        "bank account details": "बैंक खाते का विवरण",
        "direct income support to farmer families with regular transfer of financial benefit at three-monthly intervals": (
            "किसान परिवारों को हर तीन महीने में वित्तीय लाभ के नियमित हस्तांतरण के साथ प्रत्यक्ष आय सहायता"
        ),
        "all farmer families irrespective of landholding size. scheduled castes and scheduled tribes also eligible": (
            "भूमि के आकार की परवाह किए बिना सभी किसान परिवार। अनुसूचित जाति और अनुसूचित जनजाति भी पात्र हैं"
        ),
    },
    "mr": {
        "home": "मुख्यपृष्ठ",
        "schemes": "योजना",
        "dashboard": "डॅशबोर्ड",
        "login": "लॉग इन",
        "logout": "लॉग आउट",
        "apply now": "आता अर्ज करा",
        "official website": "अधिकृत वेबसाइट",
        "search": "शोधा",
        "submit": "सबमिट करा",
        "cancel": "रद्द करा",
        "save": "जतन करा",
        "notifications": "सूचना",
        "listen": "ऐका",
        "listen in": "या भाषेत ऐका",
        "select voice language": "आवाजाची भाषा निवडा",
        "pm kisan samman nidhi": "पीएम किसान सन्मान निधी",
        "eligibility": "पात्रता",
        "documents": "कागदपत्रे",
        "benefits": "फायदे",
        "all farmers": "सर्व शेतकरी",
        "eligible farmers": "पात्र शेतकरी",
        "aadhaar card": "आधार कार्ड",
        "land records": "जमिनीचे अभिलेख",
        "bank account details": "बँक खात्याचा तपशील",
        "direct income support to farmer families with regular transfer of financial benefit at three-monthly intervals": (
            "शेतकरी कुटुंबांना दर तीन महिन्यांनी आर्थिक लाभाचे नियमित हस्तांतरण करून थेट उत्पन्न सहाय्य"
        ),
        "all farmer families irrespective of landholding size. scheduled castes and scheduled tribes also eligible": (
            "जमीनधारणेच्या आकाराची पर्वा न करता सर्व शेतकरी कुटुंबे. अनुसूचित जाती आणि अनुसूचित जमाती देखील पात्र आहेत"
        ),
    },
    "te": {
        "home": "హోమ్",
        "schemes": "పథకాలు",
        "dashboard": "డాష్‌బోర్డ్",
        "login": "లాగిన్",
        "logout": "లాగ్ అవుట్",
        "apply now": "ఇప్పుడే దరఖాస్తు చేయండి",
        "official website": "అధికారిక వెబ్‌సైట్",
        "search": "వెతకండి",
        "submit": "సమర్పించండి",
        "cancel": "రద్దు చేయండి",
        "save": "భద్రపరచండి",
        "notifications": "నోటిఫికేషన్లు",
        "listen": "వినండి",
        "listen in": "ఈ భాషలో వినండి",
        "select voice language": "వాయిస్ భాషను ఎంచుకోండి",
        "pm kisan samman nidhi": "పీఎం కిసాన్ సమ్మాన్ నిధి",
        "eligibility": "అర్హత",
        "documents": "పత్రాలు",
        "benefits": "ప్రయోజనాలు",
        "all farmers": "అన్ని రైతులు",
        "eligible farmers": "అర్హత కలిగిన రైతులు",
        "aadhaar card": "ఆధార్ కార్డు",
        "land records": "భూమి రికార్డులు",
        "bank account details": "బ్యాంకు ఖాతా వివరాలు",
        "direct income support to farmer families with regular transfer of financial benefit at three-monthly intervals": (
            "రైతు కుటుంబాలకు ప్రతి మూడు నెలలకు ఆర్థిక ప్రయోజనాన్ని క్రమం తప్పకుండా బదిలీ చేసే ప్రత్యక్ష ఆదాయ సహాయం"
        ),
        "all farmer families irrespective of landholding size. scheduled castes and scheduled tribes also eligible": (
            "భూమి పరిమాణంతో సంబంధం లేకుండా అన్ని రైతు కుటుంబాలు. షెడ్యూల్డ్ కులాలు మరియు షెడ్యూల్డ్ తెగలు కూడా అర్హులు"
        ),
    },
}


def lookup_local_translation(text: str, language: str) -> LocalTranslation:
    """Return an exact local translation without guessing at unknown text."""
    normalized_text = " ".join((text or "").strip().split()).casefold()
    normalized_language = (language or "").strip().lower()
    translated = _CATALOG.get(normalized_language, {}).get(normalized_text)
    if translated is None:
        return LocalTranslation(text=None, available=False)
    return LocalTranslation(text=translated, available=True)
