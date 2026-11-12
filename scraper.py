import os
import json
import requests
from urllib.parse import urljoin, unquote
from playwright.sync_api import sync_playwright

# Save files directly into your web app's static directory
AUDIO_DIR = os.path.join("static", "native_audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

# The main directory page you provided
DIRECTORY_URL = "https://bunpro.jp/ja/grammar_points"
MAX_PAGES = 3  # Change this to scrape more pages at once


def download_audio(url, filename):
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)


def scrape_bunpro():
    sentences_db = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        print("Opening Bunpro. Please log in.")
        page.goto("https://bunpro.jp/login")

        # Pause the script until you manually log in and press Enter in the terminal
        input("Press Enter here in the terminal AFTER you have successfully logged in...")

        # 1. Go to the main directory and harvest grammar page links
        print(f"Loading directory: {DIRECTORY_URL}")
        page.goto(DIRECTORY_URL)
        page.wait_for_load_state("networkidle")

        # Find all links that point to individual grammar points
        # Adjusting selector to catch links containing '/grammar_points/'
        hrefs = page.evaluate("""() => {
            const links = Array.from(document.querySelectorAll('a'));
            return links
                .map(a => a.getAttribute('href'))
                .filter(href => href && href.includes('/grammar_points/') && href.split('/').length > 3);
        }""")

        # Remove duplicates and limit the number of pages to scrape
        unique_urls = list(set(hrefs))[:MAX_PAGES]
        print(f"Found grammar points. Scraping the first {len(unique_urls)} pages...")

        # 2. Iterate through the discovered URLs
        for path in unique_urls:
            full_url = urljoin("https://bunpro.jp", path)
            print(f"Scraping: {full_url}")
            page.goto(full_url)
            page.wait_for_load_state("networkidle")

            # Bunpro's DOM structure
            examples = page.locator('.grammar-point-example').all()

            for i, example in enumerate(examples):
                try:
                    jp_text = example.locator('.japanese-example-sentence').inner_text()
                    jp_text = jp_text.replace('\n', '').strip()

                    audio_btn = example.locator('[data-audio-url]')
                    if audio_btn.count() > 0:
                        audio_path = audio_btn.get_attribute('data-audio-url')
                        audio_url = urljoin("https://bunpro.jp", audio_path)

                        # unquote() turns '%E3%81%A0' into 'だ'
                        grammar_name = unquote(path.split('/')[-1])
                        safe_name = f"{grammar_name}_{i}.mp3"
                        local_filepath = os.path.join(AUDIO_DIR, safe_name)

                        download_audio(audio_url, local_filepath)

                        sentences_db.append({
                            "id": safe_name,
                            "text": jp_text,
                            "audio_file": f"native_audio/{safe_name}"
                        })
                except Exception as e:
                    print(f"Skipped an example due to missing data: {e}")

        browser.close()

    # Save or update the JSON database
    db_path = os.path.join("static", "sentences.json")

    # If a database already exists, append to it instead of overwriting
    if os.path.exists(db_path):
        with open(db_path, "r", encoding="utf-8") as f:
            existing_db = json.load(f)
            # Avoid adding exact duplicates
            existing_ids = {item['id'] for item in existing_db}
            new_entries = [item for item in sentences_db if item['id'] not in existing_ids]
            sentences_db = existing_db + new_entries

    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(sentences_db, f, ensure_ascii=False, indent=4)

    print(f"Scraping complete. Database now has {len(sentences_db)} sentences at {db_path}.")


if __name__ == "__main__":
    scrape_bunpro()