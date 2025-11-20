#!/usr/bin/env python3
"""
amazon_mobile_project_full.py

Full internship-project script (educational):
 - Scrapes Amazon.in search results for a query (mobile phones)
 - Parses product title, price, rating, review count, link, ASIN
 - Saves raw CSV, cleaned CSV
 - Produces simple analysis and plots (price distribution, top brands)
 - Generates a PDF report including screenshots, tables, and plots

USAGE:
    python amazon_mobile_project_full.py --query "mobile phones" --pages 2

NOTES & WARNINGS:
 - Scraping Amazon may violate their Terms of Service. Use responsibly.
 - Consider using Amazon Product Advertising API for production/legal use.
 - This template uses Selenium + BeautifulSoup for rendering JS content.
 - If scraping fails, this script falls back to a bundled sample dataset.

Author: ChatGPT (educational template)
"""

import argparse
import csv
import os
import time
import random
from urllib.parse import urljoin, urlencode
from pathlib import Path
import re
import io

# Data & plotting
import pandas as pd
import matplotlib.pyplot as plt

# Web parsing/rendering
from bs4 import BeautifulSoup

# Selenium imports (for dynamic pages)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# PDF generation
from fpdf import FPDF

# ---------------------------
# Helper / parsing functions
# ---------------------------
def build_search_url(query, page=1):
    base = "https://www.amazon.in/s"
    params = {"k": query}
    if page > 1:
        params["page"] = page
    return base + "?" + urlencode(params)

def parse_search_page(html):
    """
    Parse Amazon search page HTML for product blocks and extract fields.
    Returns list of dicts.
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []
    results = soup.select("div.s-main-slot div.s-result-item")
    for r in results:
        try:
            asin = r.get("data-asin", "").strip()
            # title
            title_tag = r.select_one("h2 a span")
            title = title_tag.get_text(strip=True) if title_tag else None
            # link
            link_tag = r.select_one("h2 a")
            link = urljoin("https://www.amazon.in", link_tag.get("href")) if link_tag else None
            # price
            price_whole = r.select_one("span.a-price-whole")
            price_frac = r.select_one("span.a-price-fraction")
            if price_whole:
                price = price_whole.get_text(strip=True) + (price_frac.get_text(strip=True) if price_frac else "")
            else:
                price = None
            # rating
            rating_tag = r.select_one("span.a-icon-alt")
            rating = rating_tag.get_text(strip=True) if rating_tag else None
            # reviews
            reviews_tag = r.select_one("span.a-size-base")
            reviews = reviews_tag.get_text(strip=True) if reviews_tag else None

            if title:
                items.append({
                    "asin": asin,
                    "title": title,
                    "price_raw": price,
                    "rating_raw": rating,
                    "reviews_raw": reviews,
                    "link": link
                })
        except Exception:
            continue
    return items

# ---------------------------
# Scraper (Selenium)
# ---------------------------
def scrape_amazon(query, pages=1, headless=True, max_wait=12, pause_range=(2.0, 5.0)):
    """
    Uses Selenium to fetch Amazon search pages and parse them.
    Returns list of product dicts.
    """
    print("[*] Starting Selenium browser (Chrome)")
    opts = Options()
    # Headless mode recommended for automation; but if debugging, set headless=False
    opts.add_argument("--headless=new" if headless else "--headless=chrome")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1280,1024")
    # Realistic user-agent
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    # Prevent detection as much as possible (note: not guaranteed)
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option('useAutomationExtension', False)

    driver = None
    try:
        driver = webdriver.Chrome(ChromeDriverManager().install(), options=opts)
    except Exception as e:
        print("[!] Could not start Chrome webdriver:", e)
        return []

    all_items = []
    try:
        for p in range(1, pages + 1):
            url = build_search_url(query, page=p)
            print(f"[*] Opening page {p}: {url}")
            driver.get(url)
            # Wait for main results container
            try:
                WebDriverWait(driver, max_wait).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.s-main-slot"))
                )
            except Exception:
                print("[!] Wait timeout; continuing after short sleep")
                time.sleep(3)
            html = driver.page_source
            # Save screenshot of first page
            if p == 1:
                ss_path = f"screenshot_search_page_{int(time.time())}.png"
                driver.save_screenshot(ss_path)
                print("[*] Saved page screenshot as", ss_path)
            items = parse_search_page(html)
            print(f"    -> Found {len(items)} items on page {p}")
            all_items.extend(items)
            # Polite randomized delay
            time.sleep(random.uniform(*pause_range))
    finally:
        if driver:
            driver.quit()

    return all_items

# ---------------------------
# Cleaning & formatting
# ---------------------------
def clean_and_transform(items):
    """
    Convert raw scraped rows into cleaned DataFrame with numeric columns.
    """
    if not items or len(items) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(items)
    # normalize price: remove non-digit chars, convert to int
    def parse_price(p):
        if not p or not isinstance(p, str):
            return None
        # Remove currency symbols, commas, spaces. Keep digits.
        digits = re.sub(r"[^\d]", "", p)
        return int(digits) if digits.isdigit() else None

    def parse_rating(r):
        if not r or not isinstance(r, str):
            return None
        m = re.search(r"([0-9]+(\.[0-9]+)?)", r)
        return float(m.group(1)) if m else None

    def parse_reviews(rv):
        if not rv or not isinstance(rv, str):
            return None
        # remove commas and non-digits
        digits = re.sub(r"[^\d]", "", rv)
        return int(digits) if digits.isdigit() else None

    df["price"] = df["price_raw"].apply(parse_price)
    df["rating"] = df["rating_raw"].apply(parse_rating)
    df["reviews"] = df["reviews_raw"].apply(parse_reviews)

    # Extract a probable brand from title (first token)
    df["brand_guess"] = df["title"].apply(lambda t: t.split()[0] if isinstance(t, str) else None)

    # Reorder columns
    cols = ["asin", "title", "brand_guess", "price_raw", "price", "rating_raw", "rating", "reviews_raw", "reviews", "link"]
    df = df[[c for c in cols if c in df.columns]]
    return df

# ---------------------------
# Sample dataset fallback
# ---------------------------
SAMPLE_CSV = """brand_model,price_inr,rating,reviews,product_link,asin
Samsung Galaxy F14,₹9,999,4.2 out of 5,12345,https://www.amazon.in/dp/B0XXX1,B0XXX1
Xiaomi Redmi 13 5G,₹11,499,4.1 out of 5,8432,https://www.amazon.in/dp/B0XXX2,B0XXX2
Realme Narzo 60,₹13,499,4.0 out of 5,5678,https://www.amazon.in/dp/B0XXX3,B0XXX3
OnePlus Nord CE4,₹18,999,4.3 out of 5,3210,https://www.amazon.in/dp/B0XXX4,B0XXX4
POCO M6 Pro,₹10,999,4.1 out of 5,4890,https://www.amazon.in/dp/B0XXX5,B0XXX5
iQOO Z10x,₹16,499,4.2 out of 5,2456,https://www.amazon.in/dp/B0XXX6,B0XXX6
Vivo Y200,₹14,999,4.0 out of 5,2100,https://www.amazon.in/dp/B0XXX7,B0XXX7
Oppo A78,₹12,999,4.1 out of 5,1890,https://www.amazon.in/dp/B0XXX8,B0XXX8
Motorola G54,₹13,499,4.0 out of 5,1234,https://www.amazon.in/dp/B0XXX9,B0XXX9
Infinix Note 40,₹11,999,4.2 out of 5,2345,https://www.amazon.in/dp/B0XXX10,B0XXX10
Samsung Galaxy A15,₹12,499,4.1 out of 5,3001,https://www.amazon.in/dp/B0XXX11,B0XXX11
Apple iPhone 14 (Refurb),₹49,999,4.4 out of 5,25678,https://www.amazon.in/dp/B0XXX12,B0XXX12
"""

def load_sample_df():
    df = pd.read_csv(io.StringIO(SAMPLE_CSV))
    # normalize column names to match cleaned format
    df = df.rename(columns={"brand_model": "title", "price_inr": "price_raw", "rating": "rating_raw", "reviews": "reviews_raw", "product_link": "link"})
    # convert price formatting to match parse expectations
    return clean_and_transform(df.to_dict(orient="records"))

# ---------------------------
# Analysis & plotting
# ---------------------------
def analyze_and_plot(df, output_dir):
    """
    Produce analysis plots (saved to files) and return summary stats.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plots = {}

    summary = {}
    summary['num_rows'] = len(df)
    summary['price_present'] = df["price"].notna().sum() if "price" in df else 0
    summary['avg_price'] = float(df["price"].dropna().mean()) if "price" in df and df["price"].dropna().size>0 else None
    summary['avg_rating'] = float(df["rating"].dropna().mean()) if "rating" in df and df["rating"].dropna().size>0 else None

    # Price histogram
    if "price" in df and df["price"].dropna().size > 0:
        plt.figure(figsize=(8,4))
        df["price"].dropna().astype(int).hist(bins=10)
        plt.title("Price distribution (INR)")
        plt.xlabel("Price (INR)")
        plt.ylabel("Count")
        p1 = output_dir / "price_histogram.png"
        plt.tight_layout()
        plt.savefig(p1, dpi=200)
        plt.close()
        plots['price_histogram'] = str(p1)

    # Top brands by count (using brand_guess)
    if "brand_guess" in df:
        top = df["brand_guess"].value_counts().head(8)
        plt.figure(figsize=(8,4))
        top.plot(kind="bar")
        plt.title("Top brands (guessed from title)")
        plt.xlabel("Brand")
        plt.ylabel("Count")
        p2 = output_dir / "top_brands.png"
        plt.tight_layout()
        plt.savefig(p2, dpi=200)
        plt.close()
        plots['top_brands'] = str(p2)

    # Simple scatter price vs rating (if both available)
    if "price" in df and "rating" in df and df["price"].dropna().size>0 and df["rating"].dropna().size>0:
        plt.figure(figsize=(6,4))
        plt.scatter(df["price"], df["rating"])
        plt.title("Price vs Rating")
        plt.xlabel("Price (INR)")
        plt.ylabel("Rating")
        p3 = output_dir / "price_vs_rating.png"
        plt.tight_layout()
        plt.savefig(p3, dpi=200)
        plt.close()
        plots['price_vs_rating'] = str(p3)

    return summary, plots

# ---------------------------
# PDF Report creation
# ---------------------------
class SimplePDFReport:
    def __init__(self, title="Amazon Mobile Scraping Report", author="Intern"):
        self.pdf = FPDF()
        self.title = title
        self.author = author

    def header(self, title=None):
        self.pdf.set_font("Arial", 'B', 16)
        self.pdf.cell(0, 10, title or self.title, ln=True, align='C')
        self.pdf.ln(4)

    def add_paragraph(self, text, size=11):
        self.pdf.set_font("Arial", size='', style='', size=size)
        # multi_cell auto-wrap
        self.pdf.multi_cell(0, 6, text)
        self.pdf.ln(2)

    def add_image(self, img_path, w=160):
        # center image
        self.pdf.image(img_path, x=(210-w)/2, w=w)
        self.pdf.ln(4)

    def add_table_from_df(self, df, max_rows=10):
        # Very simple table: header row + up to max_rows of data
        if df is None or len(df) == 0:
            return
        self.pdf.set_font("Arial", 'B', 10)
        col_w = 190 / min(len(df.columns), 5)  # naive
        # header
        for c in df.columns[:5]:
            self.pdf.cell(col_w, 7, str(c), border=1)
        self.pdf.ln()
        self.pdf.set_font("Arial", size=9)
        for _, row in df.head(max_rows).iterrows():
            for c in df.columns[:5]:
                text = str(row[c]) if not pd.isna(row[c]) else ""
                # reduce long text
                if len(text) > 40: text = text[:37] + "..."
                self.pdf.cell(col_w, 6, text, border=1)
            self.pdf.ln()
        self.pdf.ln(3)

    def save(self, path):
        self.pdf.output(path)
        print("[*] Saved PDF report to", path)

def generate_pdf_report(output_dir, df, summary, plots, screenshots=[]):
    r = SimplePDFReport(title="Amazon Mobile Phones Scraping Report", author="Intern")
    r.pdf.add_page()
    r.header()
    r.add_paragraph("Project: Web Scraping of Amazon (Mobile Phones) and Data Analysis", size=12)
    r.add_paragraph("Author: Intern\nDate: " + time.strftime("%Y-%m-%d %H:%M:%S"), size=10)

    r.add_paragraph("1. Objective:", size=11)
    r.add_paragraph("Collect product data (title, price, rating, reviews, link) from Amazon search results for mobile phones and analyze the collected dataset.", size=10)

    r.add_paragraph("2. Methodology:", size=11)
    r.add_paragraph("This project used Selenium to render pages and BeautifulSoup to parse HTML. The script extracts product blocks, cleans numeric fields, and performs basic visual analysis.", size=10)

    r.add_paragraph("3. Summary Statistics:", size=11)
    stats_text = f"Number of rows: {summary.get('num_rows')}\\nPrice values present: {summary.get('price_present')}\\nAverage price (INR): {summary.get('avg_price')}\\nAverage rating: {summary.get('avg_rating')}"
    r.add_paragraph(stats_text, size=10)

    r.add_paragraph("4. Sample of collected data:", size=11)
    r.add_table_from_df(df, max_rows=8)

    # add plots
    for k, p in plots.items():
        r.add_paragraph(f"Plot: {k.replace('_',' ').title()}", size=11)
        try:
            r.add_image(p, w=160)
        except Exception as e:
            r.add_paragraph(f"[Could not add image: {p}] Error: {e}", size=9)

    # add screenshots
    if screenshots:
        r.add_paragraph("5. Screenshots captured during scraping:", size=11)
        for s in screenshots:
            try:
                r.add_image(s, w=160)
            except Exception:
                pass

    # conclusion
    r.add_paragraph("6. Conclusion:", size=11)
    r.add_paragraph("The scraped dataset can be used for price comparisons, trend analysis and further modeling. Ensure legal compliance when scraping live sites; consider APIs for production.", size=10)

    out_pdf = Path(output_dir) / "amazon_mobile_project_report.pdf"
    r.save(str(out_pdf))
    return str(out_pdf)

# ---------------------------
# Main runner
# ---------------------------
def main():
    parser = argparse.ArgumentParser(description="Full Amazon mobile phones project (educational).")
    parser.add_argument("--query", type=str, default="mobile phones", help="Search query")
    parser.add_argument("--pages", type=int, default=1, help="Number of search result pages to scrape")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--output-dir", type=str, default="project_output", help="Directory to place outputs")
    args = parser.parse_args()

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 1) Attempt live scraping
    scraped_items = []
    try:
        scraped_items = scrape_amazon(args.query, pages=args.pages, headless=args.headless)
    except Exception as e:
        print("[!] Scraping raised an exception:", e)
        scraped_items = []

    # 2) If scraping produced no items, fallback to sample dataset
    screenshots = []
    if scraped_items and len(scraped_items) > 0:
        print("[*] Scraping succeeded with", len(scraped_items), "items")
        df_raw = pd.DataFrame(scraped_items)
        raw_csv = outdir / "mobile_dataset_raw.csv"
        df_raw.to_csv(raw_csv, index=False)
        print("[*] Wrote raw CSV to", raw_csv)
        # If a screenshot file was saved by Selenium, move it to output dir
        for fname in os.listdir("."):
            if fname.startswith("screenshot_search_page_") and fname.endswith(".png"):
                dest = outdir / fname
                os.replace(fname, dest)
                screenshots.append(str(dest))
    else:
        print("[!] No scraped data (empty or blocked). Using built-in sample dataset for demonstration.")
        df_clean = load_sample_df()
        # Save sample as CSV
        csvpath = outdir / "mobile_dataset_sample_used.csv"
        df_clean.to_csv(csvpath, index=False)
        print("[*] Sample dataset saved to", csvpath)
        # Create a screenshot-like image of the sample table for report:
        try:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(10, 4 + 0.25*len(df_clean)))
            ax.axis('off')
            table = ax.table(cellText=df_clean.head(12).values, colLabels=df_clean.head(12).columns, loc='center', cellLoc='left')
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            table.scale(1, 1.2)
            plt.title("Sample Mobile Phones Dataset (used as fallback)", fontsize=12)
            screenshot_path = outdir / "fallback_dataset_table.png"
            plt.savefig(screenshot_path, bbox_inches='tight', dpi=200)
            plt.close(fig)
            screenshots.append(str(screenshot_path))
        except Exception as e:
            print("[!] Could not create fallback screenshot:", e)
        # proceed to analysis with sample df
        df_clean = df_clean

    # If we have scraped items, clean them; if not we already have df_clean
    if scraped_items and len(scraped_items) > 0:
        df_clean = clean_and_transform(scraped_items)

    # Save cleaned CSV
    cleaned_csv = outdir / "mobile_dataset_cleaned.csv"
    df_clean.to_csv(cleaned_csv, index=False)
    print("[*] Saved cleaned dataset to", cleaned_csv)

    # Analysis & plots
    summary, plots = analyze_and_plot(df_clean, outdir)
    print("[*] Analysis summary:", summary)
    # collect plots as images
    for k, p in plots.items():
        print("   -", k, ":", p)

    # Add any existing screenshot files from current folder
    # (move them to output dir if they exist)
    for fname in os.listdir("."):
        if fname.startswith("screenshot_page") and fname.endswith(".png"):
            dest = outdir / fname
            try:
                os.replace(fname, dest)
                screenshots.append(str(dest))
            except Exception:
                pass

    # Generate PDF report
    pdf_path = generate_pdf_report(outdir, df_clean, summary, plots, screenshots=screenshots)
    print("[*] Project completed. All outputs in folder:", outdir)
    print("[*] PDF report at:", pdf_path)

if __name__ == "__main__":
    main()
