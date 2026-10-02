
from flask import Flask, render_template, request, send_file
from PIL import Image, ImageFile
from PIL.ExifTags import TAGS
import os
import re
import requests
import socket
import ipaddress
from urllib.parse import urlparse, urljoin

# Allow Pillow to handle slightly incomplete JPEG files
ImageFile.LOAD_TRUNCATED_IMAGES = True

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =========================================================
# XMP DETECTION
# =========================================================

def detect_xmp(file_path):
    """
    Looks inside the image file for common XMP metadata markers.
    Returns True if XMP metadata appears to be present.
    """

    try:
        with open(file_path, "rb") as file:
            data = file.read()

        xmp_markers = [
            b"http://ns.adobe.com/xap/1.0/",
            b"<x:xmpmeta",
            b"<?xpacket",
            b"<rdf:RDF"
        ]

        return any(marker in data for marker in xmp_markers)

    except Exception:
        return False


# =========================================================
# IPTC DETECTION
# =========================================================

def detect_iptc(file_path):
    """
    Looks for common IPTC/Photoshop metadata markers.
    """

    try:
        with open(file_path, "rb") as file:
            data = file.read()

        iptc_markers = [
            b"Photoshop 3.0",
            b"8BIM"
        ]

        return any(marker in data for marker in iptc_markers)

    except Exception:
        return False


# =========================================================
# HOME PAGE
# =========================================================

@app.route("/")
def home():
    return render_template("index.html")


# ==========================================================
# PHOTO PRIVACY SCANNER PAGE
# ==========================================================

@app.route("/photo-scan")
def photo_scan():
    return render_template("photo_scan.html")


# ==========================================================
# BROWSER PRIVACY SCANNER
# ==========================================================

@app.route("/browser-scan")
def browser_scan():
    return render_template("browser.html")


# =========================================================
# SCAN PHOTO
# =========================================================

@app.route("/scan", methods=["POST"])
def scan():

    if "photo" not in request.files:
        return "No photo was uploaded."

    photo = request.files["photo"]

    if photo.filename == "":
        return "Please select a photo."

    file_path = os.path.join(
        UPLOAD_FOLDER,
        photo.filename
    )

    photo.save(file_path)

    # Remember image for cleaning stage
    app.config["CURRENT_IMAGE"] = file_path


    # =====================================================
    # XMP + IPTC CHECK
    # =====================================================

    xmp_found = detect_xmp(file_path)
    iptc_found = detect_iptc(file_path)

    print("XMP detected:", xmp_found)
    print("IPTC detected:", iptc_found)


    # =====================================================
    # READ EXIF
    # =====================================================

    image = Image.open(file_path)
    exif_data = image.getexif()

    device_brand = "Not found"
    device_model = "Not found"
    date_time = "Not found"


    # =====================================================
    # DEVICE INFORMATION + TIMESTAMP
    # =====================================================

    for tag_id, value in exif_data.items():

        tag_name = TAGS.get(tag_id, tag_id)

        if tag_name == "Make":
            device_brand = str(value)

        elif tag_name == "Model":
            device_model = str(value)

        elif tag_name == "DateTime":
            date_time = str(value)


    # =====================================================
    # GPS INFORMATION
    # =====================================================

    gps_found = False
    latitude = None
    longitude = None

    try:

        gps_data = exif_data.get_ifd(0x8825)

        if gps_data:

            latitude_data = gps_data.get(2)
            latitude_ref = gps_data.get(1)

            longitude_data = gps_data.get(4)
            longitude_ref = gps_data.get(3)

            if latitude_data and longitude_data:

                def convert_to_decimal(coordinates):

                    degrees = float(coordinates[0])
                    minutes = float(coordinates[1])
                    seconds = float(coordinates[2])

                    return (
                        degrees
                        + minutes / 60
                        + seconds / 3600
                    )

                latitude = convert_to_decimal(latitude_data)
                longitude = convert_to_decimal(longitude_data)

                if latitude_ref == "S":
                    latitude = -latitude

                if longitude_ref == "W":
                    longitude = -longitude

                gps_found = True

    except Exception:
        gps_found = False


    # =====================================================
    # PRIVACY SAFETY SCORE
    # =====================================================

    privacy_score = 100

    if gps_found:
        privacy_score -= 40

    device_found = (
        device_brand != "Not found"
        or device_model != "Not found"
    )

    if device_found:
        privacy_score -= 25

    if date_time != "Not found":
        privacy_score -= 20

    # Extra hidden metadata risk
    if xmp_found:
        privacy_score -= 10

    if iptc_found:
        privacy_score -= 5

    privacy_score = max(privacy_score, 0)


    # =====================================================
    # SAVE BEFORE-CLEANING INFORMATION
    # =====================================================

    app.config["BEFORE_BRAND"] = device_brand
    app.config["BEFORE_MODEL"] = device_model
    app.config["BEFORE_TIME"] = date_time
    app.config["BEFORE_GPS"] = gps_found
    app.config["BEFORE_XMP"] = xmp_found
    app.config["BEFORE_IPTC"] = iptc_found
    
    app.config["BEFORE_SCORE"] = privacy_score

    


    # =====================================================
    # SHOW SCAN RESULT
    # =====================================================

    return render_template(
        "result.html",

        brand=device_brand,
        model=device_model,
        date_time=date_time,

        gps_found=gps_found,
        latitude=latitude,
        longitude=longitude,

        xmp_found=xmp_found,
        iptc_found=iptc_found,

        privacy_score=privacy_score
    )


# =========================================================
# REMOVE DIGITAL TATTOO + VERIFY
# =========================================================

@app.route("/clean", methods=["POST"])
def clean():

    file_path = app.config.get("CURRENT_IMAGE")

    if not file_path:
        return "No image available to clean."


    # =====================================================
    # CREATE CLEAN IMAGE
    # =====================================================

    with Image.open(file_path) as image:

        image.load()

        # Reconstruct only the visible pixels.
        # We intentionally do not copy EXIF metadata.
        clean_image = image.convert("RGB")

        clean_path = os.path.join(
            UPLOAD_FOLDER,
            "clean_photo.jpg"
        )

        clean_image.save(
            clean_path,
            "JPEG",
            quality=95
        )


    # =====================================================
    # RESCAN CLEANED IMAGE
    # =====================================================

    with Image.open(clean_path) as verify_image:

        clean_exif = verify_image.getexif()
# Check whether XMP still exists after cleaning
        after_xmp = detect_xmp(clean_path)

# Check whether IPTC still exists after cleaning
        after_iptc = detect_iptc(clean_path)
        after_brand = "Not found"
        after_model = "Not found"
        after_time = "Not found"
        after_gps = False

        for tag_id, value in clean_exif.items():

            tag_name = TAGS.get(tag_id, tag_id)

            if tag_name == "Make":
                after_brand = str(value)

            elif tag_name == "Model":
                after_model = str(value)

            elif tag_name == "DateTime":
                after_time = str(value)

        try:

            clean_gps_data = clean_exif.get_ifd(0x8825)

            if clean_gps_data:
                after_gps = True

        except Exception:
            after_gps = False


    # =====================================================
    # RESCAN XMP + IPTC
    # =====================================================

    after_xmp = detect_xmp(clean_path)
    after_iptc = detect_iptc(clean_path)


    # =====================================================
    # GET ORIGINAL VALUES
    # =====================================================

    before_brand = app.config.get(
        "BEFORE_BRAND",
        "Not found"
    )

    before_model = app.config.get(
        "BEFORE_MODEL",
        "Not found"
    )

    before_time = app.config.get(
        "BEFORE_TIME",
        "Not found"
    )

    before_gps = app.config.get(
        "BEFORE_GPS",
        False
    )

    before_score = app.config.get(
        "BEFORE_SCORE",
        100
    )

    before_xmp = app.config.get(
        "BEFORE_XMP",
        False
    )

    before_iptc = app.config.get(
        "BEFORE_IPTC",
        False
    )


    # =====================================================
    # CALCULATE AFTER-CLEANING SCORE
    # =====================================================

    after_score = 100

    if after_gps:
        after_score -= 40

    after_device_found = (
        after_brand != "Not found"
        or after_model != "Not found"
    )

    if after_device_found:
        after_score -= 25

    if after_time != "Not found":
        after_score -= 20

    if after_xmp:
        after_score -= 10

    if after_iptc:
        after_score -= 5

    after_score = max(after_score, 0)


    # =====================================================
    # FINAL VERIFICATION
    # =====================================================

    metadata_removed = (
        after_brand == "Not found"
        and after_model == "Not found"
        and after_time == "Not found"
        and after_gps is False
        and after_xmp is False
        and after_iptc is False
    )


    # =====================================================
    # SHOW VERIFICATION PAGE
    # =====================================================

    return render_template(
        "clean.html",

        # BEFORE
        before_brand=before_brand,
        before_model=before_model,
        before_time=before_time,
        before_gps=before_gps,
        before_score=before_score,
        before_xmp=before_xmp,
        before_iptc=before_iptc,

        # AFTER
        after_brand=after_brand,
        after_model=after_model,
        after_time=after_time,
        after_gps=after_gps,
        after_score=after_score,
        after_xmp=after_xmp,
        after_iptc=after_iptc,

        # Verification
        metadata_removed=metadata_removed
    )


# =========================================================
# DOWNLOAD CLEAN PHOTO
# =========================================================

@app.route("/download")

def download_clean_photo():

    clean_path = os.path.join(
        UPLOAD_FOLDER,
        "clean_photo.jpg"
    )

    if not os.path.exists(clean_path):
        return "No cleaned photo is available."

    return send_file(
        clean_path,
        as_attachment=True,
        download_name="Digital_Tattoo_Clean_Photo.jpg"
    )


# =========================================================
# WEBSITE PRIVACY SCANNER
# =========================================================

# Security headers tested by the Website Privacy Scanner
SECURITY_HEADERS = [
    "Content-Security-Policy",
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Permissions-Policy",
    "X-Frame-Options",
]

# Recognizable tracking/analytics indicator patterns
TRACKING_INDICATORS = [
    {"name": "Google Analytics", "pattern": r"google-analytics\.com|googletagmanager\.com/gtag/js|ga\.js|analytics\.js"},
    {"name": "Google Tag Manager", "pattern": r"googletagmanager\.com/gtm\.js|googletagmanager\.com/ns\.html"},
    {"name": "Meta/Facebook Pixel", "pattern": r"connect\.facebook\.net|facebook\.com/tr|fbevents\.js"},
    {"name": "Hotjar", "pattern": r"hotjar\.com|hj\.js"},
    {"name": "Mixpanel", "pattern": r"mixpanel\.com"},
    {"name": "Segment", "pattern": r"segment\.com|segment\.io"},
    {"name": "Amplitude", "pattern": r"amplitude\.com"},
    {"name": "Matomo", "pattern": r"matomo\.js|piwik\.js"},
    {"name": "Plausible", "pattern": r"plausible\.io"},
    {"name": "Cloudflare Insights", "pattern": r"static\.cloudflareinsights\.com"},
]


def validate_url_for_scan(url):
    """
    SSRF protection: validate that a URL is safe to scan.
    Only public HTTP/HTTPS websites are allowed.
    Returns (is_safe, message).
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format."

    # Only allow HTTP and HTTPS schemes
    if parsed.scheme not in ("http", "https"):
        return False, "Only HTTP and HTTPS websites can be scanned."

    hostname = parsed.hostname
    if not hostname:
        return False, "No hostname was found in the URL."

    # Block well-known internal hostnames
    blocked_hostnames = [
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
    ]
    if hostname.lower() in blocked_hostnames:
        return False, "Internal hostnames cannot be scanned."

    # Block cloud metadata endpoints by hostname
    if hostname == "169.254.169.254":
        return False, "Cloud metadata endpoints cannot be scanned."

    # Resolve hostname and verify all resolved IPs are public
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, "The hostname could not be resolved."

    if not addr_infos:
        return False, "The hostname could not be resolved."

    for addr_info in addr_infos:
        ip_str = addr_info[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, "The hostname resolved to an invalid IP address."

        # Reject non-public IP addresses
        if ip_obj.is_loopback:
            return False, "Loopback addresses cannot be scanned."
        if ip_obj.is_private:
            return False, "Private network addresses cannot be scanned."
        if ip_obj.is_link_local:
            return False, "Link-local addresses cannot be scanned."
        if ip_obj.is_reserved:
            return False, "Reserved IP addresses cannot be scanned."
        if ip_obj.is_multicast:
            return False, "Multicast addresses cannot be scanned."

    return True, "URL passed validation."


def analyze_cookies(set_cookie_headers, https_active):
    """
    Parse Set-Cookie headers and identify privacy-relevant attributes.
    Returns (cookies_list, scoring_issues).
    """
    cookies = []
    issues = []

    for cookie_header in set_cookie_headers:
        parts = cookie_header.split(";")
        name = parts[0].strip().split("=")[0].strip() if parts else "Unknown"

        attributes = [p.strip().lower() for p in parts[1:]]
        has_secure = "secure" in attributes
        has_httponly = "httponly" in attributes

        samesite = None
        for attr in attributes:
            if attr.startswith("samesite"):
                samesite = attr.split("=")[-1].strip()

        cookies.append({
            "name": name,
            "secure": has_secure,
            "httponly": has_httponly,
            "samesite": samesite,
        })

    # Cookie scoring: only add points for specific observable reasons
    if https_active:
        insecure_cookies = [c for c in cookies if not c["secure"]]
        if insecure_cookies:
            issues.append({
                "label": "Cookie(s) without Secure attribute",
                "detail": ", ".join(c["name"] for c in insecure_cookies) +
                          " — these cookies were sent over HTTPS without the Secure flag.",
                "points": 5,
            })

    non_httponly = [c for c in cookies if not c["httponly"]]
    if non_httponly:
        issues.append({
            "label": "Cookie(s) without HttpOnly attribute",
            "detail": ", ".join(c["name"] for c in non_httponly) +
                      " — these cookies can be read by client-side scripts.",
            "points": 5,
        })

    return cookies, issues


def extract_third_party_domains(html_content, base_hostname):
    """
    Extract unique third-party domains from HTML resource references.
    Compares resource hostnames against the scanned website's hostname.
    """
    domains = set()

    # Resource URL patterns to search for in HTML
    patterns = [
        r'<script[^>]+src=["\']([^"\']+)["\']',
        r'<img[^>]+src=["\']([^"\']+)["\']',
        r'<link[^>]+href=["\']([^"\']+)["\']',
        r'<iframe[^>]+src=["\']([^"\']+)["\']',
        r'<source[^>]+src=["\']([^"\']+)["\']',
        r'<video[^>]+src=["\']([^"\']+)["\']',
        r'<audio[^>]+src=["\']([^"\']+)["\']',
        r'@import\s+["\']([^"\']+)["\']',
        r'url\(["\']?([^"\')]+)["\']?\)',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, html_content, re.IGNORECASE)
        for match in matches:
            try:
                parsed = urlparse(match)
                if parsed.hostname and parsed.hostname.lower() != base_hostname.lower():
                    domains.add(parsed.hostname.lower())
            except Exception:
                continue

    return sorted(domains)


def detect_tracking_indicators(html_content):
    """
    Detect recognizable tracking/analytics indicators in HTML content.
    Returns a list of indicator names found.
    """
    indicators = []
    text_to_search = html_content

    for indicator in TRACKING_INDICATORS:
        if re.search(indicator["pattern"], text_to_search, re.IGNORECASE):
            indicators.append(indicator["name"])

    return indicators


def calculate_exposure_score(analysis):
    """
    Calculate the observed-exposure score using a transparent additive model.
    Every point added has a corresponding visible reason in the breakdown.
    """
    breakdown = []
    score = 0

    # +5 for each of the six security headers not observed (max 30)
    missing_headers = [
        h for h, observed in analysis["security_headers"].items()
        if not observed
    ]
    if missing_headers:
        points = len(missing_headers) * 5
        breakdown.append({
            "label": "Security headers not observed",
            "detail": ", ".join(missing_headers),
            "points": points,
        })
        score += points

    # +10 if tracking/analytics indicators observed
    if analysis["tracking_indicators"]:
        breakdown.append({
            "label": "Tracking/analytics indicator observed",
            "detail": ", ".join(analysis["tracking_indicators"]),
            "points": 10,
        })
        score += 10

    # +5 if Referrer-Policy not observed
    if not analysis["security_headers"].get("Referrer-Policy"):
        breakdown.append({
            "label": "Referrer-Policy not observed",
            "detail": "The website did not send a Referrer-Policy header.",
            "points": 5,
        })
        score += 5

    # +5 if Permissions-Policy not observed
    if not analysis["security_headers"].get("Permissions-Policy"):
        breakdown.append({
            "label": "Permissions-Policy not observed",
            "detail": "The website did not send a Permissions-Policy header.",
            "points": 5,
        })
        score += 5

    # +20 if connection is HTTP (not HTTPS)
    if not analysis["https_active"]:
        breakdown.append({
            "label": "Connection not using HTTPS",
            "detail": "The website was scanned over an unencrypted HTTP connection.",
            "points": 20,
        })
        score += 20

    # Cookie-related points (only for specific observable reasons)
    for issue in analysis.get("cookie_issues", []):
        breakdown.append(issue)
        score += issue["points"]

    # Cap at 100
    score = min(score, 100)

    # Classify into exposure levels
    if score <= 29:
        level = "low"
        level_text = "Low Observed Exposure"
    elif score <= 59:
        level = "medium"
        level_text = "Moderate Observed Exposure"
    else:
        level = "high"
        level_text = "High Observed Exposure"

    return {
        "score": score,
        "level": level,
        "level_text": level_text,
        "breakdown": breakdown,
    }


def perform_website_scan(url):
    """
    Perform a passive privacy/security scan of a public website.
    Returns a dictionary with all analysis results, or an error.
    """
    # Validate URL (SSRF protection)
    is_safe, message = validate_url_for_scan(url)
    if not is_safe:
        return {"error": message}

    # Ensure URL has a scheme
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Follow redirects manually, validating each target
    max_redirects = 5
    current_url = url
    redirect_chain = []

    for _ in range(max_redirects):
        is_safe, message = validate_url_for_scan(current_url)
        if not is_safe:
            return {"error": f"Redirect target was blocked: {message}"}

        try:
            response = requests.get(
                current_url,
                timeout=10,
                allow_redirects=False,
                headers={
                    "User-Agent": "DigitalTattoo-PrivacyScanner/1.0 (Educational Tool)"
                },
                stream=True,
            )
        except requests.exceptions.Timeout:
            return {"error": "The website took too long to respond (timeout)."}
        except requests.exceptions.ConnectionError:
            return {"error": "Could not connect to the website."}
        except requests.exceptions.RequestException as e:
            return {"error": f"Could not fetch the website: {str(e)}"}

        # Handle redirect
        if response.status_code in (301, 302, 303, 307, 308):
            redirect_url = response.headers.get("Location")
            if redirect_url:
                current_url = urljoin(current_url, redirect_url)
                redirect_chain.append(current_url)
                continue
            break
        else:
            break

    final_url = current_url

    # Capture Set-Cookie headers before reading body
    set_cookie_headers = []
    try:
        if hasattr(response, "raw") and response.raw and hasattr(response.raw, "headers"):
            raw_headers = response.raw.headers
            if hasattr(raw_headers, "getlist"):
                set_cookie_headers = raw_headers.getlist("Set-Cookie")
            elif hasattr(raw_headers, "get"):
                val = raw_headers.get("Set-Cookie")
                if val:
                    set_cookie_headers = [val]
    except Exception:
        pass

    # Read response body with size limit (5 MB max)
    max_size = 5 * 1024 * 1024
    content = b""
    try:
        for chunk in response.iter_content(chunk_size=8192):
            content += chunk
            if len(content) > max_size:
                return {"error": "The website response was too large to analyze."}
    except Exception as e:
        return {"error": f"Error reading the website response: {str(e)}"}

    # Decode content for HTML analysis
    try:
        html_content = content.decode("utf-8", errors="replace")
    except Exception:
        html_content = ""

    # Determine HTTPS status
    https_active = final_url.startswith("https://")

    # Analyze security headers
    response_headers = {k.lower(): v for k, v in response.headers.items()}
    security_headers = {}
    for header in SECURITY_HEADERS:
        security_headers[header] = response_headers.get(header.lower()) is not None

    # Analyze cookies
    cookies, cookie_issues = analyze_cookies(set_cookie_headers, https_active)

    # Extract third-party domains from HTML
    base_hostname = urlparse(final_url).hostname or ""
    third_party_domains = extract_third_party_domains(html_content, base_hostname)

    # Detect tracking/analytics indicators
    tracking_indicators = detect_tracking_indicators(html_content)

    # Compile analysis
    analysis = {
        "requested_url": url,
        "final_url": final_url,
        "redirect_chain": redirect_chain,
        "hostname": base_hostname,
        "status_code": response.status_code,
        "https_active": https_active,
        "security_headers": security_headers,
        "cookies": cookies,
        "cookie_issues": cookie_issues,
        "third_party_domains": third_party_domains,
        "tracking_indicators": tracking_indicators,
        "referrer_policy": response_headers.get("referrer-policy"),
        "permissions_policy": response_headers.get("permissions-policy"),
    }

    # Calculate exposure score
    score_result = calculate_exposure_score(analysis)
    analysis["score"] = score_result["score"]
    analysis["level"] = score_result["level"]
    analysis["level_text"] = score_result["level_text"]
    analysis["breakdown"] = score_result["breakdown"]

    return analysis


# ==========================================================
# WEBSITE PRIVACY SCANNER PAGE
# ==========================================================

@app.route("/website-scan", methods=["GET", "POST"])
def website_scan():
    if request.method == "POST":
        url = request.form.get("url", "").strip()

        if not url:
            return render_template(
                "website_scan.html",
                error="Please enter a website URL.",
                show_results=False,
            )

        result = perform_website_scan(url)

        if "error" in result:
            return render_template(
                "website_scan.html",
                error=result["error"],
                show_results=False,
                scanned_url=url,
            )

        return render_template(
            "website_scan.html",
            result=result,
            show_results=True,
            error=None,
        )

    return render_template(
        "website_scan.html",
        show_results=False,
        error=None,
    )


# =========================================================
# START FLASK
# =========================================================

if __name__ == "__main__":
    app.run(debug=True)