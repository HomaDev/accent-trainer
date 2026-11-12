import os
import json
import requests
import re
from urllib.parse import unquote
from playwright.sync_api import sync_playwright

AUDIO_DIR = os.path.join("static", "native_audio")
SESSION_FILE = "bunpro_session.json"
os.makedirs(AUDIO_DIR, exist_ok=True)


def download_male_audio(url, filename):
    # Fallback to force the URL to point to the male audio directory
    if "female_audio" in url:
        url = url.replace("female_audio", "male_audio")
    elif "female" in url:
        url = url.replace("female", "male")

    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        return True
    return False


def login_and_save_session():
    """Opens a browser for the user to log in manually, then saves the session state."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print("\n" + "=" * 50)
        print("FIRST TIME SETUP: LOGIN REQUIRED")
        print("1. A browser window will open to the Bunpro login page.")
        print("2. Please log in with your email and password.")
        print("3. Once you see your dashboard, return to this terminal and press ENTER.")
        print("=" * 50 + "\n")

        page.goto("https://bunpro.jp/login")
        input("Press ENTER here after you have successfully logged in...")

        # Save cookies and local storage to a file
        context.storage_state(path=SESSION_FILE)
        browser.close()
        print("Session saved successfully! You won't need to log in next time.\n")


def scrape_bunpro_page(url):
    sentences_db = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        # Load the saved session cookies so Bunpro recognizes your account
        context = browser.new_context(storage_state=SESSION_FILE)
        page = context.new_page()

        network_audio_urls = []
        page.on("request",
                lambda req: network_audio_urls.append(req.url) if ".mp3" in req.url or ".m4a" in req.url else None)

        page.add_init_script("""
            window.capturedAudio = [];
            const originalPlay = HTMLAudioElement.prototype.play;
            HTMLAudioElement.prototype.play = function() {
                if (this.src) { window.capturedAudio.push(this.src); }
                return originalPlay.apply(this, arguments);
            };
        """)

        print(f"\nLoading page: {url}")
        page.goto(url)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        print("Switching to the Examples (例文) tab...")
        try:
            examples_tab = page.locator('button[aria-controls="例文"], button[aria-controls="Examples"]').first
            if examples_tab.is_visible():
                examples_tab.click(force=True)
                page.wait_for_timeout(1000)
        except Exception:
            pass

        print("\n" + "=" * 50)
        print("Opening Settings menu...")
        try:
            settings_gear = page.locator(
                'header#examples ~ header button[title*="設定"], header#examples ~ header button[title*="Settings"]').first
            if settings_gear.is_visible():
                settings_gear.scroll_into_view_if_needed()
                settings_gear.click(force=True)
        except Exception:
            print("Could not auto-click the settings gear. Please click it yourself!")

        print("Waiting 10 SECONDS for you to manually click the Male voice...")
        print("=" * 50 + "\n")
        page.wait_for_timeout(10000)

        # Target ONLY the sentences strictly inside the "Examples" container
        examples_list = page.locator('header#examples ~ ul').first
        examples = examples_list.locator('li[id^="study-question-"]').all()

        print(f"Found {len(examples)} sentences in the Examples section. Scraping ALL of them...\n")

        for i, example in enumerate(examples):
            try:
                jp_element = example.locator('p[data-force-furigana]')
                if jp_element.count() == 0:
                    continue

                jp_text = jp_element.first.inner_text().replace('\n', '').strip()
                play_btn = example.locator('button[title="再生"], button[title="Play"]').first
                audio_url = None

                if play_btn.count() > 0:
                    page.evaluate("window.capturedAudio = []")
                    network_audio_urls.clear()

                    play_btn.scroll_into_view_if_needed()
                    play_btn.click(force=True)

                    page.wait_for_timeout(1500)

                    captured = page.evaluate("window.capturedAudio")
                    if captured:
                        audio_url = captured[-1]

                    if not audio_url:
                        clean_jp = jp_text.replace("。", "").replace("、", "")
                        for req_url in reversed(network_audio_urls):
                            if clean_jp in unquote(req_url):
                                audio_url = req_url
                                break

                    if not audio_url and network_audio_urls:
                        audio_url = network_audio_urls[-1]

                if audio_url:
                    clean_text = re.sub(r'[\\/*?:"<>|。、！？!?\s]', '', jp_text)

                    if not clean_text:
                        grammar_name = unquote(url.split('/')[-1])
                        clean_text = f"{grammar_name}_{i}"

                    safe_name = f"{clean_text}.mp3"
                    local_filepath = os.path.join(AUDIO_DIR, safe_name)

                    print(f"[{i + 1}/{len(examples)}] Saving Audio: {safe_name}")
                    success = download_male_audio(audio_url, local_filepath)

                    if success:
                        sentences_db.append({
                            "id": safe_name,
                            "text": jp_text,
                            "audio_file": f"native_audio/{safe_name}"
                        })
                    else:
                        print(f"[{i + 1}/{len(examples)}] Failed to download audio from URL.")
                else:
                    print(f"[{i + 1}/{len(examples)}] Skipped (No audio found): {jp_text}")

            except Exception as e:
                print(f"Error on example {i + 1}: {e}")

        browser.close()

    db_path = os.path.join("static", "sentences.json")
    if os.path.exists(db_path):
        with open(db_path, "r", encoding="utf-8") as f:
            existing_db = json.load(f)
            existing_ids = {item['id'] for item in existing_db}
            new_entries = [item for item in sentences_db if item['id'] not in existing_ids]
            sentences_db = existing_db + new_entries
    else:
        sentences_db = sentences_db

    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(sentences_db, f, ensure_ascii=False, indent=4)

    print(f"\nDone! You now have {len(sentences_db)} total sentences in your database.")


if __name__ == "__main__":
    print("-" * 50)

    # Check if a session file exists before asking for a URL
    if not os.path.exists(SESSION_FILE):
        login_and_save_session()

    target_url = input("Paste the Bunpro grammar point URL to scrape:\n> ").strip()
    if target_url:
        scrape_bunpro_page(target_url)