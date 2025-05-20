import os
import hashlib
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import credentials, firestore
import spacy
from geopy.geocoders import Nominatim
import ast  # safer than eval for JSON string parsing

# Load spaCy model (make sure you installed it: python -m spacy download en_core_web_sm)
nlp = spacy.load("en_core_web_sm")

# Geolocator setup
geolocator = Nominatim(user_agent="news_scraper_geopy")

# Keywords to filter
KEYWORDS = ["rape", "murder", "harassment"]

# RSS feeds to scrape
RSS_FEEDS = [
    "https://www.thehindu.com/news/national/?service=rss",
    "https://indianexpress.com/section/india/feed/",
    "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms",
    "https://www.ndtv.com/rss/india.xml",
]

# Firebase init
def init_firebase():
    if not firebase_admin._apps:
        cred_json = os.getenv("FIREBASE_CREDENTIALS")
        if not cred_json:
            raise Exception("FIREBASE_CREDENTIALS env var not set!")
        
        # Convert string to dict safely
        cred_dict = ast.literal_eval(cred_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    
    return firestore.client()

db = None

def generate_hash(url):
    return hashlib.md5(url.encode("utf-8")).hexdigest()

def db_contains_article(url_hash):
    doc_ref = db.collection("crime_reports").document(url_hash)
    return doc_ref.get().exists

def save_to_firebase(article):
    url_hash = generate_hash(article["link"])
    if db_contains_article(url_hash):
        print(f"[SKIP] Already in DB: {article['link']}")
        return
    doc_ref = db.collection("crime_reports").document(url_hash)
    doc_ref.set(article)
    print(f"[SAVED] {article['title']}")

def extract_text_from_url(url):
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        paragraphs = soup.find_all("p")
        text = " ".join(p.get_text() for p in paragraphs)
        return text
    except Exception as e:
        print(f"Failed to fetch or parse article page: {e}")
        return ""

def extract_location(text):
    doc = nlp(text)
    locations = [ent.text for ent in doc.ents if ent.label_ in ["GPE", "LOC"]]
    return locations[0] if locations else "Unknown"

def geocode_location(location_name):
    if location_name == "Unknown":
        return 0.0, 0.0
    try:
        loc = geolocator.geocode(location_name)
        if loc:
            return loc.latitude, loc.longitude
    except Exception as e:
        print(f"Geocoding error: {e}")
    return 0.0, 0.0

def main():
    global db
    db = init_firebase()

    for feed_url in RSS_FEEDS:
        print(f"\nFetching from: {feed_url}")
        print("-" * 50)
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            title = entry.get("title", "").lower()
            summary = entry.get("summary", "").lower()
            link = entry.get("link", "")

            if not link:
                continue

            # Filter articles by keywords in title or summary
            if not any(keyword in title or keyword in summary for keyword in KEYWORDS):
                continue

            # Scrape article page for better location extraction
            article_text = extract_text_from_url(link)
            location = extract_location(article_text)
            lat, lon = geocode_location(location)

            article_data = {
                "title": entry.get("title", ""),
                "link": link,
                "publishedAt": entry.get("published", datetime.now(timezone.utc).isoformat()),
                "summary": entry.get("summary", ""),
                "location": location,
                "latitude": lat,
                "longitude": lon,
                "severity": "critical",
            }

            save_to_firebase(article_data)

if __name__ == "__main__":
    main()
