1"""
=============================================================================
  🚗  RoadRescue — Workshop Management & Breakdown Assistance System
       AI-Enhanced with Google Gemini 1.5 Flash — Version 2.0
=============================================================================
  Features:
    • AI Problem Diagnosis        (Google Gemini text)
    • Vehicle Damage Detection    (Gemini Vision + OpenCV fallback)
    • Nationwide Mechanic Search  (auto-invite framework, 38+ mechanics)
    • Roadside GPS Assistance     (Haversine distance, location list)
    • Multi-Payment System        (bKash, Nagad, Debit/Credit Card)
    • Beautiful Web Interface     (Flask + Tailwind CSS)
    • Full Console Mode Fallback

  Developed By: Group 8 — Tanvir-2485 | Hafiz-2450 | Shahajalal-2451
  Department of CSE, Northern University Bangladesh
=============================================================================
"""

import os
import sys
import math
import hashlib
import csv
import json\

import base64
import io
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime

# ── Optional AI / Image imports ───────────────────────────────────────────────
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import (Flask, request, jsonify, render_template_string,
                   session, redirect, url_for)

# ── Constants ─────────────────────────────────────────────────────────────────
WORKSHOP_LAT  = 23.8103
WORKSHOP_LON  = 90.4125
WORKSHOP_NAME = "RoadRescue Main Workshop — Dhaka"
VERSION       = "2.0 AI-Enhanced"
SECRET_KEY    = "roadrescue_hackathon_2024_secret"


# ═════════════════════════════════════════════════════════════════════════════
#  UTILITY HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def simple_hash(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()

def read_int(prompt: str) -> int:
    while True:
        try:
            return int(input(prompt))
        except ValueError:
            print("Invalid input! Please enter a number: ", end="")

def read_line(prompt: str) -> str:
    return input(prompt).strip()

def open_file_cross_platform(filename: str):
    try:
        if sys.platform.startswith("win"):
            os.startfile(filename)
        elif sys.platform == "darwin":
            os.system(f'open "{filename}"')
        else:
            os.system(f'xdg-open "{filename}"')
    except Exception:
        print(f"  ↳ Open '{filename}' manually.")

def _strip_price(raw: str) -> float:
    """Parse price strings like '1200.00/-' or '1200' → float."""
    cleaned = raw.strip().replace("/-", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# ═════════════════════════════════════════════════════════════════════════════
#  LOCATION CLASSES
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class NamedLocation:
    area_name: str = ""
    lat: float = 0.0
    lon: float = 0.0


class DhakaLocationDatabase:
    def __init__(self):
        self.locations: List[NamedLocation] = []

    def load(self, filename: str) -> bool:
        self.locations.clear()
        try:
            with open(filename, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"  [WARN] '{filename}' not found — roadside area list unavailable.")
            return False

        for lineno, line in enumerate(lines, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            if "\t" not in line:
                continue
            name, coord = line.split("\t", 1)
            if "," not in coord:
                continue
            try:
                lat_s, lon_s = coord.split(",", 1)
                self.locations.append(
                    NamedLocation(name.strip(), float(lat_s.strip()), float(lon_s.strip()))
                )
            except ValueError:
                pass

        return bool(self.locations)

    def find_index_by_name(self, name: str) -> int:
        lower = name.lower()
        for i, loc in enumerate(self.locations):
            if loc.area_name.lower() == lower:
                return i
        return -1


class Location:
    def __init__(self, lat: float = 0.0, lon: float = 0.0):
        self.lat = lat
        self.lon = lon

    def is_set(self) -> bool:
        return not (self.lat == 0.0 and self.lon == 0.0)

    @staticmethod
    def is_in_bangladesh(lat: float, lon: float) -> bool:
        return 20.59 <= lat <= 26.63 and 88.01 <= lon <= 92.67

    def in_bangladesh(self) -> bool:
        return Location.is_in_bangladesh(self.lat, self.lon)

    def distance_to(self, other: "Location") -> float:
        R = 6371.0
        p1, p2 = math.radians(self.lat), math.radians(other.lat)
        dp = math.radians(other.lat - self.lat)
        dl = math.radians(other.lon - self.lon)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def maps_url(self) -> str:
        return f"https://www.google.com/maps/search/?api=1&query={self.lat:.6f},{self.lon:.6f}"

    def __str__(self) -> str:
        tag = "Inside Bangladesh" if self.in_bangladesh() else "Outside Bangladesh"
        return f"{self.lat:.6f}, {self.lon:.6f} ({tag})"

    @staticmethod
    def input_from_list(loc_list: List[NamedLocation]) -> "Location":
        print("  Select your area:")
        for i, loc in enumerate(loc_list, 1):
            print(f"    {i}) {loc.area_name} ({loc.lat:.4f}, {loc.lon:.4f})")
        while True:
            ch = read_int("  Enter number: ")
            if 1 <= ch <= len(loc_list):
                lo = loc_list[ch - 1]
                if lo.lat != 0.0 and lo.lon != 0.0 and Location.is_in_bangladesh(lo.lat, lo.lon):
                    return Location(lo.lat, lo.lon)
                print("  Invalid coordinates for that area, try another.")
            else:
                print("  Invalid choice.")


# ═════════════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class Vehicle:
    reg_no:  str = ""
    brand:   str = ""
    model:   str = ""
    colour:  str = ""
    year:    int = 0

    def serialized(self) -> str:
        return f"{self.reg_no}-{self.brand}-{self.model}-{self.colour}-{self.year}"

    @staticmethod
    def deserialize(data: str) -> "Vehicle":
        parts = data.split("-", 4)
        v = Vehicle()
        if len(parts) > 0: v.reg_no = parts[0]
        if len(parts) > 1: v.brand  = parts[1]
        if len(parts) > 2: v.model  = parts[2]
        if len(parts) > 3: v.colour = parts[3]
        if len(parts) > 4:
            try: v.year = int(parts[4])
            except ValueError: pass
        return v


class Customer:
    def __init__(self, name: str = "", phone: str = "", password: str = ""):
        self.id: int = 0
        self.name = name
        self.phone = phone
        self.address = ""
        self.vehicle = Vehicle()
        self.password_hash = simple_hash(password) if password else ""
        self.has_vehicle = False

    def get_name(self) -> str:  return self.name
    def get_phone(self) -> str: return self.phone

    def check_password(self, pw: str) -> bool:
        return self.password_hash == simple_hash(pw)

    def add_vehicle(self):
        self.vehicle = Vehicle(
            reg_no = read_line("  Registration No.: "),
            brand  = read_line("  Brand: "),
            model  = read_line("  Model: "),
            colour = read_line("  Color: "),
            year   = read_int ("  Year:  ")
        )
        self.has_vehicle = True

    def show_vehicle(self):
        if not self.has_vehicle:
            print("  No vehicle registered yet.")
            return
        v = self.vehicle
        print(f"\n  Registration : {v.reg_no}")
        print(f"  Brand        : {v.brand}")
        print(f"  Model        : {v.model}")
        print(f"  Color        : {v.colour}")
        print(f"  Year         : {v.year}")


@dataclass
class Part:
    code:  str   = ""
    name:  str   = ""
    price: float = 0.0

    def display(self):
        print(f"  {self.name:<28}{self.code:<12}Tk {self.price:.2f}")

    def serialize(self) -> str:
        return f"{self.code};{self.name};{self.price}"

    @staticmethod
    def deserialize(line: str) -> "Part":
        cols = line.split(";", 2)
        code  = cols[0] if len(cols) > 0 else ""
        name  = cols[1] if len(cols) > 1 else ""
        price = _strip_price(cols[2]) if len(cols) > 2 else 0.0
        return Part(code, name, price)


@dataclass
class Mechanic:
    code:         str      = ""
    name:         str      = ""
    expertise:    str      = ""
    rate_per_job: float    = 0.0
    available:    bool     = True
    location:     Location = field(default_factory=Location)

    def display(self):
        status = "[Available]" if self.available else "[Busy]"
        print(f"  {self.name:<20}{self.code:<10}{self.expertise:<30}Tk {self.rate_per_job:.2f}  {status}")


class ServiceRequest:
    def __init__(self):
        self.id: int = 0
        self.customer_index: int = -1
        self.issue: str = ""
        self.chosen_part: Part = Part()
        self.mechanic_index: int = -1
        self.roadside: bool = False
        self.delivery_charge: float = 0.0
        self.total_amount: float = 0.0
        self.paid: bool = False
        self.payment_method: str = ""
        self.location: Location = Location()

    def get_location_string(self) -> str:
        if not self.roadside:
            return "N/A"
        if not self.location.is_set():
            return "Not Provided"
        ws = Location(WORKSHOP_LAT, WORKSHOP_LON)
        d  = self.location.distance_to(ws)
        return f"{self.location} | {d:.2f} km from workshop | {self.location.maps_url()}"


# ═════════════════════════════════════════════════════════════════════════════
#  GEMINI AI ASSISTANT
# ═════════════════════════════════════════════════════════════════════════════

class GeminiAIAssistant:
    """
    Wraps Google Gemini 1.5 Flash for:
      1. Text-based vehicle problem diagnosis
      2. Image-based damage detection (Vision)
    Falls back gracefully to keyword matching + OpenCV when no API key.
    """

    FALLBACK_KB: Dict[str, List[str]] = {
        "engine": [
            "Turn off the engine immediately to prevent further damage",
            "Check engine oil level — low/no oil causes engine seize",
            "Look for oil leaks under the vehicle",
            "Check coolant level (radiator / overflow tank)",
            "Do NOT restart if engine seized — call a mechanic",
        ],
        "tire": [
            "Move vehicle safely off the road, turn on hazard lights",
            "Inspect tire for nails, screws, or sidewall damage",
            "Check valve stem for air leak",
            "Do NOT drive on a flat tire — it ruins the rim",
            "Use spare tire if available, or call for roadside help",
        ],
        "fuel": [
            "Check fuel gauge — you may have simply run out of fuel",
            "Inspect fuel lines under the car for visible leaks",
            "Check fuel pump: turn ignition to ON — listen for pump hum",
            "Clogged fuel filter can mimic empty tank symptoms",
            "Order fuel delivery — do not attempt to siphon",
        ],
        "battery": [
            "Check battery terminals for corrosion (white/green buildup)",
            "Try jump-starting from another vehicle",
            "If battery is dead and new, check the alternator",
            "Turn off all electronics to conserve remaining charge",
            "Battery typically lasts 3-5 years — consider replacement",
        ],
        "brake": [
            "Pump brakes gently — low fluid causes soft pedal",
            "Check brake fluid reservoir under the hood",
            "Grinding noise = worn brake pads (metal on metal)",
            "Squealing noise = brake pad wear indicators triggered",
            "Do NOT drive with failed brakes — call immediately",
        ],
        "electrical": [
            "Check main fuse box (usually under dashboard or hood)",
            "Inspect battery terminals for loose connections",
            "Check alternator belt for wear/snapping",
            "Short circuits often smell like burning plastic",
            "Turn off all non-essential electrics to save power",
        ],
        "transmission": [
            "Check transmission fluid level and color",
            "Dark/burnt smelling fluid = serious problem",
            "Grinding when shifting = worn synchros or gear damage",
            "Slipping gears can indicate low fluid or clutch wear",
            "Do not force gear changes — call a transmission specialist",
        ],
        "overheating": [
            "Pull over immediately — overheating can destroy the engine",
            "Turn off AC, turn on heater to transfer heat away from engine",
            "Let engine cool 20-30 min before opening radiator cap",
            "Check coolant level in overflow tank (cold engine only)",
            "Inspect for broken radiator hose or water pump failure",
        ],
        "smoke": [
            "White smoke = coolant leak into cylinders (head gasket?)",
            "Blue smoke = oil burning (worn piston rings / valve seals)",
            "Black smoke = rich fuel mixture (injector or sensor issue)",
            "Pull over safely and turn engine off if smoke is heavy",
            "Do not continue driving with heavy smoke",
        ],
        "noise": [
            "Knocking from engine = low oil or worn bearings (serious!)",
            "Grinding when braking = brake pad replacement needed",
            "Whining from wheels = wheel bearing failure",
            "Rattling underneath = loose exhaust or heat shield",
            "Clicking on turns = CV joint or axle wear",
        ],
        "clutch": [
            "Slipping clutch = worn friction disc, needs replacement",
            "High biting point = clutch disc worn thin",
            "Spongy pedal = air in hydraulic clutch line",
            "Burning smell = clutch slipping excessively",
            "Avoid riding the clutch — keep foot off pedal when not shifting",
        ],
        "steering": [
            "Check power steering fluid level",
            "Heavy steering can indicate failed power steering pump",
            "Vibration at speed = wheel balancing needed",
            "Pulling to one side = alignment or tire pressure issue",
            "Steering knock = worn tie-rod ends or ball joints",
        ],
    }

    def __init__(self):
        self.api_key  = os.getenv("GEMINI_API_KEY", "")
        self.model    = None
        self._ready   = False

        if GEMINI_AVAILABLE and self.api_key and self.api_key not in ("your_key_here", ""):
            try:
                genai.configure(api_key=self.api_key)
                self.model  = genai.GenerativeModel("gemini-1.5-flash")
                self._ready = True
                print("  [AI] ✅ Google Gemini 1.5 Flash — initialized successfully!")
            except Exception as ex:
                print(f"  [AI] ⚠️  Gemini init failed: {ex}. Using fallback AI.")
        else:
            if not GEMINI_AVAILABLE:
                print("  [AI] ⚠️  google-generativeai not installed. Using keyword fallback.")
            else:
                print("  [AI] ⚠️  GEMINI_API_KEY not set. Using keyword fallback.")
                print("  [AI]     Get a FREE key at: https://aistudio.google.com/app/apikey")

    @property
    def is_real_ai(self) -> bool:
        return self._ready

    @property
    def status_label(self) -> str:
        return "🤖 Google Gemini 1.5 Flash" if self._ready else "🔧 Keyword AI (Fallback)"

    @property
    def badge(self) -> str:
        return "Gemini AI ✨" if self._ready else "Fallback AI"

    # ── Text Diagnosis ──────────────────────────────────────────────────────

    def diagnose_problem(self, problem: str, vehicle_info: str = "") -> Dict[str, Any]:
        if self.model:
            try:
                prompt = (
                    "You are an expert automotive mechanic AI assistant for RoadRescue "
                    "emergency breakdown service in Bangladesh.\n\n"
                    f"Customer's Vehicle: {vehicle_info or 'Not specified'}\n"
                    f"Problem Description: {problem}\n\n"
                    "Provide a structured emergency response in this exact format:\n\n"
                    "🔍 DIAGNOSIS:\n[2-3 sentences, simple language explaining what is likely wrong]\n\n"
                    "⚡ IMMEDIATE ACTIONS:\n"
                    "• [Safety step 1]\n• [Safety step 2]\n• [Step 3]\n• [Step 4]\n\n"
                    "🔧 LIKELY PARTS NEEDED:\n"
                    "• [Part 1]\n• [Part 2]\n• [Part 3]\n\n"
                    "🚦 URGENCY LEVEL: CRITICAL / HIGH / MEDIUM / LOW\n\n"
                    "🚗 SAFE TO DRIVE: Yes / No / Short distance only\n\n"
                    "💡 EXTRA TIP:\n[One practical tip for the stranded customer]\n\n"
                    "Keep the response concise and reassuring. "
                    "The customer may be stranded far from any workshop in Bangladesh."
                )
                resp = self.model.generate_content(prompt)
                return {
                    "success":      True,
                    "response":     resp.text,
                    "source":       "gemini",
                    "source_label": "🤖 Google Gemini AI",
                }
            except Exception as ex:
                pass  # fall through to keyword fallback

        # Keyword fallback
        tips = self._keyword_tips(problem)
        return {
            "success":      True,
            "response":     self._format_fallback(problem, tips),
            "source":       "fallback",
            "source_label": "🔧 Keyword AI (Fallback)",
        }

    # ── Image Analysis ──────────────────────────────────────────────────────

    def analyze_vehicle_image(self, image_bytes: bytes,
                               mime_type: str = "image/jpeg") -> Dict[str, Any]:
        if self.model:
            try:
                prompt = (
                    "You are a professional vehicle damage assessor for RoadRescue "
                    "emergency service in Bangladesh.\n\n"
                    "Carefully analyze this vehicle image and provide:\n\n"
                    "🔍 VISIBLE DAMAGE:\n• [List every damage you can see]\n\n"
                    "🔩 AFFECTED PARTS:\n• [Specific parts that are damaged]\n\n"
                    "⚠️ DAMAGE SEVERITY: Minor / Moderate / Severe / Critical\n\n"
                    "🔧 PARTS NEEDED FOR REPAIR:\n• [Parts list with estimated BDT cost]\n\n"
                    "🚨 IMMEDIATE SAFETY CONCERNS:\n• [Any urgent safety issues?]\n\n"
                    "💰 ROUGH REPAIR COST ESTIMATE (BDT):\n[Cost range in Bangladeshi Taka]\n\n"
                    "If this is not a vehicle image, say 'No vehicle detected in image.'\n"
                    "Be specific and practical for emergency roadside assistance."
                )
                image_part = {"mime_type": mime_type, "data": image_bytes}
                resp = self.model.generate_content([prompt, image_part])
                return {
                    "success":      True,
                    "analysis":     resp.text,
                    "source":       "gemini-vision",
                    "source_label": "🤖 Gemini Vision AI",
                }
            except Exception:
                pass

        return self._opencv_fallback(image_bytes)

    # ── Internal helpers ────────────────────────────────────────────────────

    def _keyword_tips(self, problem: str) -> List[str]:
        lower = problem.lower()
        tips: List[str] = []
        for key, sols in self.FALLBACK_KB.items():
            if key in lower:
                tips.extend(sols)
        if not tips:
            tips = [
                "Turn on hazard lights and move safely off the road",
                "Do not panic — stay with your vehicle",
                "Check your vehicle manual for guidance",
                "Call RoadRescue for professional help",
                "Keep engine off until mechanic arrives",
            ]
        # deduplicate, keep order
        seen: set = set()
        unique: List[str] = []
        for t in tips:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique[:6]

    def _format_fallback(self, problem: str, tips: List[str]) -> str:
        lines = [
            "🔍 DIAGNOSIS:",
            "Based on your description, here are likely issues and recommended actions.\n",
            "⚡ IMMEDIATE ACTIONS:",
        ]
        for t in tips:
            lines.append(f"  • {t}")
        lines += [
            "",
            "🚦 URGENCY LEVEL: HIGH — Please contact a mechanic promptly.",
            "",
            "💡 EXTRA TIP:",
            "  Upload a photo of the damage for more accurate AI analysis.",
            "  Set your GEMINI_API_KEY in the .env file for full AI diagnosis.",
        ]
        return "\n".join(lines)

    def _opencv_fallback(self, image_bytes: bytes) -> Dict[str, Any]:
        if not (CV2_AVAILABLE and PIL_AVAILABLE):
            return {
                "success":      True,
                "analysis":     (
                    "📷 IMAGE ANALYSIS (Basic Mode)\n\n"
                    "OpenCV/Pillow not fully installed.\n"
                    "Please install: pip install pillow opencv-python-headless\n\n"
                    "For full AI image analysis, set GEMINI_API_KEY in your .env file.\n"
                    "Get a free key at: https://aistudio.google.com/app/apikey"
                ),
                "source":       "no-cv",
                "source_label": "⚠️ Basic Mode",
            }
        try:
            img    = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            arr    = np.array(img)
            gray   = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
            edges  = cv2.Canny(gray, 100, 200)
            ed     = float(np.sum(edges > 0)) / edges.size
            hsv    = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
            rust   = cv2.inRange(hsv, np.array([0,50,50]), np.array([20,255,255]))
            rd     = float(np.sum(rust > 0)) / rust.size

            findings = []
            if ed > 0.15:
                findings.append("⚠️ High structural complexity / possible deformation detected")
            if ed > 0.25:
                findings.append("🔴 Significant edge disruption — major body damage likely")
            if rd > 0.05:
                findings.append("🟤 Rust / corrosion coloration detected")
            if rd > 0.15:
                findings.append("🔴 Extensive rust — structural integrity may be compromised")
            if not findings:
                findings.append("✅ No obvious severe damage patterns detected")

            lines = [
                "📷 BASIC IMAGE ANALYSIS (OpenCV — No Gemini Key)\n",
                "🔍 VISIBLE DAMAGE:",
            ]
            for f in findings:
                lines.append(f"  • {f}")
            lines += [
                "",
                f"📊 Edge density: {ed:.3f}  |  Rust indicator: {rd:.3f}",
                "",
                "💡 For full AI damage analysis:",
                "   Set GEMINI_API_KEY in your .env file.",
                "   Free key: https://aistudio.google.com/app/apikey",
            ]
            return {
                "success":      True,
                "analysis":     "\n".join(lines),
                "source":       "opencv",
                "source_label": "🔍 OpenCV Analysis",
            }
        except Exception as ex:
            return {
                "success":  False,
                "analysis": f"Could not process image: {ex}",
                "source":   "error",
                "source_label": "❌ Error",
            }


# ═════════════════════════════════════════════════════════════════════════════
#  NATIONWIDE MECHANIC NETWORK
# ═════════════════════════════════════════════════════════════════════════════

class NationwideMechanicNetwork:
    """
    Loads mechanics from nationwide_mechanics.json.
    Provides progressive-radius search and auto-invitation framework.
    When a user is 300+ km from the workshop, this system scans the entire
    country and invites the nearest available mechanics on their behalf.
    """

    def __init__(self, filename: str = "nationwide_mechanics.json"):
        self.mechanics: List[Dict] = []
        self.invitations: List[Dict] = []
        self._load(filename)

    def _load(self, filename: str):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                self.mechanics = json.load(f)
            print(f"  [Network] ✅ Loaded {len(self.mechanics)} nationwide mechanics.")
        except FileNotFoundError:
            print(f"  [Network] ⚠️  {filename} not found — using built-in sample mechanics.")
            self.mechanics = self._builtin_sample()
        except json.JSONDecodeError as ex:
            print(f"  [Network] ❌ JSON parse error in {filename}: {ex}")
            self.mechanics = self._builtin_sample()

    def _builtin_sample(self) -> List[Dict]:
        return [
            {"id": "BUILT001", "name": "Emergency Mechanic (Dhaka)", "expertise": "General Mechanic",
             "city": "Dhaka", "area": "Central", "lat": 23.8103, "lon": 90.4125,
             "contact": "01700-000001", "rating": 4.5, "available": True,
             "rate_per_job": 2000, "years_experience": 8, "vehicle_types": ["All"]},
            {"id": "BUILT002", "name": "Highway Mechanic (N1)", "expertise": "Engine Specialist",
             "city": "Cumilla", "area": "N1 Highway", "lat": 23.4607, "lon": 91.1809,
             "contact": "01700-000002", "rating": 4.6, "available": True,
             "rate_per_job": 2200, "years_experience": 10, "vehicle_types": ["Car", "Truck"]},
        ]

    # ── Search ──────────────────────────────────────────────────────────────

    def find_nearby(self, lat: float, lon: float,
                    max_km: float = 50.0) -> List[Dict]:
        user = Location(lat, lon)
        results = []
        for m in self.mechanics:
            try:
                dist = user.distance_to(Location(m["lat"], m["lon"]))
            except (KeyError, TypeError):
                continue
            if dist <= max_km:
                entry = dict(m)
                entry["distance_km"] = round(dist, 2)
                results.append(entry)
        return sorted(results, key=lambda x: x["distance_km"])

    # ── Auto-invite (progressive radius) ────────────────────────────────────

    def auto_search_and_invite(self, lat: float, lon: float,
                               issue: str,
                               customer_name: str = "Customer") -> Dict[str, Any]:
        """
        Progressively expands search radius: 25 → 50 → 100 → 200 → 500 km.
        Sends invitations to the 3 nearest available mechanics found.
        """
        for radius in (25, 50, 100, 200, 500):
            found     = self.find_nearby(lat, lon, radius)
            available = [m for m in found if m.get("available", True)]
            if not available:
                continue

            invited = []
            for m in available[:3]:
                inv = {
                    "id":           m["id"],
                    "name":         m["name"],
                    "expertise":    m["expertise"],
                    "city":         m["city"],
                    "area":         m.get("area", ""),
                    "distance_km":  m["distance_km"],
                    "contact":      m["contact"],
                    "rating":       m.get("rating", 4.0),
                    "rate_per_job": m.get("rate_per_job", 1500),
                    "customer_name": customer_name,
                    "issue":        issue,
                    "timestamp":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "status":       "Invitation Sent ✅",
                }
                invited.append(inv)
                self.invitations.append(inv)

            return {
                "found":                   True,
                "search_radius_km":        radius,
                "total_mechanics_in_radius": len(found),
                "mechanics_invited":       len(invited),
                "invited_mechanics":       invited,
                "message": (
                    f"Found {len(found)} mechanic(s) within {radius} km. "
                    f"Invitation sent to {len(invited)} nearest available mechanic(s)!"
                ),
            }

        return {
            "found":                   False,
            "search_radius_km":        500,
            "total_mechanics_in_radius": 0,
            "mechanics_invited":       0,
            "invited_mechanics":       [],
            "message": (
                "No mechanics found nationwide within 500 km. "
                "Our main workshop team will dispatch immediately. "
                "Please call our emergency line: 01700-RESCUE"
            ),
        }

    # ── Invite specific mechanic ─────────────────────────────────────────────

    def invite_specific(self, mechanic_id: str, issue: str,
                        lat: float, lon: float,
                        customer_name: str = "Customer") -> Dict[str, Any]:
        for m in self.mechanics:
            if m.get("id") == mechanic_id:
                inv = {
                    "id":           m["id"],
                    "name":         m["name"],
                    "expertise":    m["expertise"],
                    "city":         m["city"],
                    "contact":      m["contact"],
                    "customer_name": customer_name,
                    "issue":        issue,
                    "lat":          lat,
                    "lon":          lon,
                    "timestamp":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "status":       "Invitation Sent ✅",
                }
                self.invitations.append(inv)
                return {"success": True, "message": f"Invitation sent to {m['name']}!", "mechanic": inv}
        return {"success": False, "message": "Mechanic not found in network."}

    def get_all(self) -> List[Dict]:
        return self.mechanics


# ═════════════════════════════════════════════════════════════════════════════
#  SYSTEM DATA MANAGER  (parts file)
# ═════════════════════════════════════════════════════════════════════════════

class SystemDataManager:
    def __init__(self):
        self._parts_by_key: Dict[str, List[Tuple[Part, str]]] = {}
        self._all_parts: List[Part] = []

    def load_parts_file(self, filename: str) -> bool:
        try:
            with open(filename, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            return False

        for line in lines:
            line = line.strip()
            if not line:
                continue
            cols = line.split(";")
            if len(cols) < 5:
                continue
            key, brand, code, name = cols[0].strip(), cols[1].strip(), cols[2].strip(), cols[3].strip()
            price = _strip_price(cols[4])

            p = Part(code, name, price)
            self._all_parts.append(p)

            for k in (key.lower(), brand.lower()):
                if k:
                    self._parts_by_key.setdefault(k, []).append(
                        (p, "model" if k == key.lower() else "brand")
                    )
            self._parts_by_key.setdefault("any", []).append((p, "any"))

        return bool(self._all_parts)

    def save_parts_file(self, filename: str) -> bool:
        try:
            with open(filename, "w", encoding="utf-8") as f:
                for p in self._all_parts:
                    f.write(f"ANY;ANY;{p.code};{p.name};{p.price}\n")
            return True
        except IOError:
            return False

    def get_parts_for_vehicle(self, model: str, brand: str) -> List[Tuple[Part, str]]:
        def priority(s: str) -> int:
            return {"model": 3, "brand": 2}.get(s, 1)

        by_code: Dict[str, Tuple[Part, str]] = {}
        for k in (model.lower(), brand.lower(), "any"):
            for p, mt in self._parts_by_key.get(k, []):
                if p.code not in by_code or priority(mt) > priority(by_code[p.code][1]):
                    by_code[p.code] = (p, mt)

        result = list(by_code.values())
        result.sort(key=lambda x: (-priority(x[1]), x[0].name))
        return result

    def add_part_fallback(self, p: Part):
        self._all_parts.append(p)
        self._parts_by_key.setdefault("any", []).append((p, "any"))

    def get_all_parts(self) -> List[Part]:
        return self._all_parts


# ═════════════════════════════════════════════════════════════════════════════
#  HTML TEMPLATES
# ═════════════════════════════════════════════════════════════════════════════

_NAV = (
    '<nav class="bg-gray-800 border-b border-gray-700 px-6 py-3 sticky top-0 z-50 shadow-xl">'
    '<div class="max-w-7xl mx-auto flex items-center justify-between">'
    '<a href="/" class="flex items-center gap-3">'
    '<div class="w-10 h-10 bg-gradient-to-br from-orange-500 to-red-600 rounded-full '
    'flex items-center justify-center text-xl">🚗</div>'
    '<div>'
    '<div class="text-lg font-bold leading-tight">'
    '<span class="text-orange-400">Road</span><span class="text-white">Rescue</span>'
    '</div>'
    '<div class="text-xs text-gray-400">AI Emergency Vehicle Assistance</div>'
    '</div>'
    '</a>'
    '<div class="flex items-center gap-5 text-sm">'
    '<a href="/" class="text-gray-300 hover:text-orange-400 transition-colors">🏠 Home</a>'
    '<a href="/ai" class="text-gray-300 hover:text-orange-400 transition-colors">🤖 AI Assistant</a>'
    '<a href="/mechanics" class="text-gray-300 hover:text-orange-400 transition-colors">🔍 Find Mechanic</a>'
    '<a href="/customer" class="text-gray-300 hover:text-orange-400 transition-colors">👤 Customer</a>'
    '<a href="/admin" class="bg-orange-600 hover:bg-orange-700 px-3 py-1.5 rounded-lg font-medium transition-colors">🛡️ Admin</a>'
    '</div>'
    '</div>'
    '</nav>'
)

_FOOT = (
    '<footer class="bg-gray-800 border-t border-gray-700 py-8 mt-12">'
    '<div class="max-w-7xl mx-auto px-6 text-center">'
    '<div class="text-3xl mb-2">🚗</div>'
    '<p class="text-orange-400 font-bold text-lg">RoadRescue v2.0 AI-Enhanced</p>'
    '<p class="text-gray-400 text-sm mt-1">'
    'Group 8 — Tanvir-2485 | Hafiz-2450 | Shahajalal-2451'
    '</p>'
    '<p class="text-gray-500 text-xs mt-1">Department of CSE, Northern University Bangladesh</p>'
    '<div class="flex flex-wrap justify-center gap-4 mt-4 text-xs text-gray-500">'
    '<span>🤖 Google Gemini AI</span><span>•</span>'
    '<span>🔧 38+ Nationwide Mechanics</span><span>•</span>'
    '<span>💳 bKash | Nagad | Card</span><span>•</span>'
    '<span>📍 GPS Location</span>'
    '</div>'
    '</div>'
    '</footer>'
    '</body></html>'
)

_HEAD = (
    '<!DOCTYPE html><html lang="en"><head>'
    '<meta charset="UTF-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    '<title>{{ page_title }} — RoadRescue</title>'
    '<script src="https://cdn.tailwindcss.com"></script>'
    '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">'
    '<style>'
    'body{font-family:"Segoe UI",system-ui,sans-serif}'
    'pre{white-space:pre-wrap;word-wrap:break-word;font-family:inherit;line-height:1.7}'
    '.fade-in{animation:fadeIn .4s ease}'
    '@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}'
    '.spin{animation:spin 1s linear infinite}'
    '@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}'
    '.card-hover{transition:all .2s}'
    '.card-hover:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(0,0,0,.35)}'
    '</style>'
    '</head>'
    '<body class="bg-gray-900 text-white min-h-screen flex flex-col">'
)


def _page(content: str) -> str:
    return _HEAD + _NAV + '<div class="flex-1">' + content + '</div>' + _FOOT


# ── Home ─────────────────────────────────────────────────────────────────────
HOME_TMPL = _page("""
<div class="max-w-7xl mx-auto px-6 py-12">
  <div class="text-center py-12">
    <div class="text-6xl mb-4">🚗💥🔧</div>
    <h1 class="text-4xl md:text-5xl font-extrabold mb-4 leading-tight">
      Stranded on the Road?<br>
      <span class="text-orange-400">We've Got You Covered!</span>
    </h1>
    <p class="text-gray-400 text-lg mb-8 max-w-2xl mx-auto">
      AI-powered emergency vehicle assistance anywhere in Bangladesh.
      Describe your problem, upload a photo, find the nearest mechanic — instantly.
    </p>
    <div class="flex flex-wrap justify-center gap-4">
      <a href="/ai" class="bg-orange-600 hover:bg-orange-700 px-8 py-4 rounded-xl text-lg font-bold transition-all transform hover:scale-105 shadow-lg shadow-orange-900/40">
        🤖 Get AI Help — Free!
      </a>
      <a href="/mechanics" class="bg-gray-700 hover:bg-gray-600 border border-gray-600 px-8 py-4 rounded-xl text-lg font-bold transition-all">
        🔍 Find Nearest Mechanic
      </a>
    </div>
  </div>

  <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mt-4">
    <a href="/ai" class="bg-gray-800 border border-gray-700 hover:border-orange-500 rounded-xl p-6 text-center group transition-all card-hover">
      <div class="text-4xl mb-3">🤖</div>
      <h3 class="text-lg font-bold text-orange-400 mb-2">AI Diagnosis</h3>
      <p class="text-gray-400 text-sm">Describe your problem or upload a photo for instant AI-powered damage detection and solutions.</p>
      <div class="mt-4 text-orange-400 text-sm">Try AI Assistant →</div>
    </a>
    <a href="/mechanics" class="bg-gray-800 border border-gray-700 hover:border-blue-500 rounded-xl p-6 text-center group transition-all card-hover">
      <div class="text-4xl mb-3">📍</div>
      <h3 class="text-lg font-bold text-blue-400 mb-2">Find Mechanic</h3>
      <p class="text-gray-400 text-sm">Our system searches 38+ certified mechanics nationwide — even 300 km+ from the workshop.</p>
      <div class="mt-4 text-blue-400 text-sm">Find Mechanics →</div>
    </a>
    <a href="/customer" class="bg-gray-800 border border-gray-700 hover:border-green-500 rounded-xl p-6 text-center group transition-all card-hover">
      <div class="text-4xl mb-3">🛠️</div>
      <h3 class="text-lg font-bold text-green-400 mb-2">Request Service</h3>
      <p class="text-gray-400 text-sm">Order parts and a mechanic to your exact location. Pay via bKash, Nagad, or Card.</p>
      <div class="mt-4 text-green-400 text-sm">Request Service →</div>
    </a>
  </div>

  <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mt-10 bg-gray-800 rounded-xl p-6 border border-gray-700">
    <div class="text-center"><div class="text-3xl font-bold text-orange-400">38+</div><div class="text-gray-400 text-sm mt-1">Nationwide Mechanics</div></div>
    <div class="text-center"><div class="text-3xl font-bold text-blue-400">10+</div><div class="text-gray-400 text-sm mt-1">Cities Covered</div></div>
    <div class="text-center"><div class="text-3xl font-bold text-green-400">24/7</div><div class="text-gray-400 text-sm mt-1">Emergency Support</div></div>
    <div class="text-center"><div class="text-3xl font-bold text-purple-400">5</div><div class="text-gray-400 text-sm mt-1">Payment Methods</div></div>
  </div>

  <div class="mt-12">
    <h2 class="text-2xl font-bold text-center mb-8">⚡ How It Works</h2>
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-5 text-center">
        <div class="text-3xl mb-2">1️⃣</div><h4 class="font-bold text-orange-400">Register</h4>
        <p class="text-gray-400 text-sm mt-1">Sign up with your vehicle details</p>
      </div>
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-5 text-center">
        <div class="text-3xl mb-2">2️⃣</div><h4 class="font-bold text-orange-400">AI Diagnose</h4>
        <p class="text-gray-400 text-sm mt-1">Describe problem or upload photo for instant AI analysis</p>
      </div>
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-5 text-center">
        <div class="text-3xl mb-2">3️⃣</div><h4 class="font-bold text-orange-400">Find Mechanic</h4>
        <p class="text-gray-400 text-sm mt-1">AI finds nearest mechanic and sends auto-invitation</p>
      </div>
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-5 text-center">
        <div class="text-3xl mb-2">4️⃣</div><h4 class="font-bold text-orange-400">Get Help</h4>
        <p class="text-gray-400 text-sm mt-1">Mechanic arrives with parts. Pay digitally!</p>
      </div>
    </div>
  </div>

  <div class="mt-10 bg-gray-800 border border-gray-700 rounded-xl p-6 text-center">
    <p class="text-gray-300 font-medium mb-4">💳 Accepted Payment Methods</p>
    <div class="flex flex-wrap justify-center gap-3">
      <span class="bg-green-900/40 border border-green-700 px-4 py-2 rounded-lg text-sm">💚 bKash</span>
      <span class="bg-orange-900/40 border border-orange-700 px-4 py-2 rounded-lg text-sm">🟠 Nagad</span>
      <span class="bg-blue-900/40 border border-blue-700 px-4 py-2 rounded-lg text-sm">💳 Debit Card</span>
      <span class="bg-purple-900/40 border border-purple-700 px-4 py-2 rounded-lg text-sm">💳 Credit Card</span>
      <span class="bg-gray-700 border border-gray-600 px-4 py-2 rounded-lg text-sm">💵 Cash on Delivery</span>
    </div>
  </div>
</div>
""")


# ── AI Assistant ──────────────────────────────────────────────────────────────
AI_TMPL = _page("""
<div class="max-w-7xl mx-auto px-6 py-8">
  <div class="flex items-center gap-3 mb-6">
    <div class="w-12 h-12 bg-gradient-to-br from-orange-500 to-red-600 rounded-full flex items-center justify-center text-2xl">🤖</div>
    <div>
      <h2 class="text-2xl font-bold">AI Vehicle Assistant</h2>
      <p class="text-gray-400 text-sm">{{ ai_status }} — describe your problem or upload a photo</p>
    </div>
  </div>

  <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
    <!-- LEFT: Input -->
    <div class="space-y-4">
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-5">
        <h3 class="font-bold text-orange-400 mb-3">💬 Describe Your Problem</h3>
        <textarea id="problemText" rows="4"
          placeholder="e.g., My engine suddenly stopped. There is smoke coming from under the hood..."
          class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm resize-none focus:border-orange-500 focus:outline-none placeholder-gray-600"></textarea>
        <input id="vehicleInfo" placeholder="Your Vehicle (e.g., Toyota Corolla 2018)"
          class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm mt-2 focus:border-orange-500 focus:outline-none placeholder-gray-600">
        <button onclick="diagnoseIssue()" id="diagBtn"
          class="w-full mt-3 bg-orange-600 hover:bg-orange-700 py-3 rounded-lg font-bold text-sm transition-colors">
          🤖 Get AI Diagnosis
        </button>
      </div>

      <div class="bg-gray-800 border border-gray-700 rounded-xl p-5">
        <h3 class="font-bold text-blue-400 mb-3">📷 Upload Vehicle Photo for Damage Detection</h3>
        <div id="dropZone" onclick="document.getElementById('imageInput').click()"
          class="border-2 border-dashed border-gray-600 hover:border-blue-500 rounded-lg p-6 text-center cursor-pointer transition-colors">
          <div class="text-3xl mb-2">📷</div>
          <p class="text-gray-400 text-sm">Click or drag & drop a vehicle photo</p>
          <p class="text-gray-600 text-xs mt-1">AI will detect damage, rust, affected parts & repair cost</p>
        </div>
        <input type="file" id="imageInput" accept="image/*" class="hidden" onchange="previewImage(this)">
        <div id="imgPrev" class="hidden mt-3 space-y-2">
          <img id="previewImg" class="w-full h-44 object-cover rounded-lg border border-gray-700">
          <button onclick="analyzeImage()" id="analyzeBtn"
            class="w-full bg-blue-600 hover:bg-blue-700 py-2.5 rounded-lg font-bold text-sm transition-colors">
            🔍 Analyze Damage with AI
          </button>
        </div>
      </div>

      <div class="bg-gray-800 border border-gray-700 rounded-xl p-5">
        <h3 class="font-bold text-green-400 mb-3">📍 Find Mechanics Near You</h3>
        <div class="grid grid-cols-2 gap-2 mb-2">
          <input id="uLat" type="number" step="0.0001" placeholder="Latitude (e.g. 23.8103)"
            class="bg-gray-900 border border-gray-600 rounded-lg p-2.5 text-sm focus:border-green-500 focus:outline-none placeholder-gray-600">
          <input id="uLon" type="number" step="0.0001" placeholder="Longitude (e.g. 90.4125)"
            class="bg-gray-900 border border-gray-600 rounded-lg p-2.5 text-sm focus:border-green-500 focus:outline-none placeholder-gray-600">
        </div>
        <select id="sRadius" class="w-full bg-gray-900 border border-gray-600 rounded-lg p-2.5 text-sm mb-2 focus:outline-none">
          <option value="25">Within 25 km</option>
          <option value="50" selected>Within 50 km</option>
          <option value="100">Within 100 km</option>
          <option value="200">Within 200 km</option>
          <option value="500">Nationwide (500 km)</option>
        </select>
        <div class="grid grid-cols-2 gap-2">
          <button onclick="findMechanics()" class="bg-green-600 hover:bg-green-700 py-2.5 rounded-lg font-bold text-sm transition-colors">🔍 Find</button>
          <button onclick="autoInvite()" class="bg-purple-600 hover:bg-purple-700 py-2.5 rounded-lg font-bold text-sm transition-colors">📨 Auto-Invite</button>
        </div>
        <button onclick="useGPS()" class="w-full mt-2 bg-gray-700 hover:bg-gray-600 py-2 rounded-lg text-xs transition-colors">
          📡 Use Browser GPS
        </button>
      </div>
    </div>

    <!-- RIGHT: Chat + Results -->
    <div class="space-y-4">
      <div class="bg-gray-800 border border-gray-700 rounded-xl flex flex-col" style="min-height:440px">
        <div class="flex items-center gap-3 p-4 border-b border-gray-700">
          <div class="w-8 h-8 bg-gradient-to-br from-orange-500 to-red-600 rounded-full flex items-center justify-center text-sm">🤖</div>
          <div class="flex-1">
            <span class="font-bold text-sm">RoadRescue AI</span>
            <span id="aiBadge" class="ml-2 text-xs bg-gray-700 px-2 py-0.5 rounded-full text-gray-400">{{ ai_badge }}</span>
          </div>
          <div id="spinner" class="hidden w-4 h-4 border-2 border-orange-500 border-t-transparent rounded-full spin"></div>
        </div>
        <div id="chatBox" class="p-4 space-y-3 overflow-y-auto flex-1" style="max-height:550px">
          <div class="bg-gray-700/60 rounded-lg p-3 text-sm text-gray-300 fade-in">
            👋 <strong>Hello! I'm your AI vehicle assistant.</strong><br><br>
            I can help you with:<br>
            • 🔍 Diagnosing your vehicle problem<br>
            • 📷 Detecting damage from photos<br>
            • 📍 Finding the nearest mechanics<br>
            • 📨 Sending invitations to available mechanics<br><br>
            <em class="text-gray-500">Powered by {{ ai_badge }}</em>
          </div>
        </div>
      </div>

      <div id="mechBox" class="hidden bg-gray-800 border border-gray-700 rounded-xl p-5">
        <h3 id="mechBoxTitle" class="font-bold text-green-400 mb-3">🔧 Mechanics Found</h3>
        <div id="mechList" class="space-y-3"></div>
      </div>
    </div>
  </div>
</div>

<script>
function addMsg(html, isUser=false) {
  const box = document.getElementById('chatBox');
  const d = document.createElement('div');
  d.className = 'p-3 rounded-lg text-sm fade-in ' +
    (isUser ? 'bg-gray-700/60 border border-gray-600 ml-4' : 'bg-orange-900/20 border border-orange-800/40');
  d.innerHTML = html;
  box.appendChild(d);
  box.scrollTop = box.scrollHeight;
}
function setLoad(on) {
  document.getElementById('spinner').classList.toggle('hidden', !on);
}
function diagnoseIssue() {
  const prob = document.getElementById('problemText').value.trim();
  const veh  = document.getElementById('vehicleInfo').value.trim();
  if (!prob) { alert('Please describe your problem first!'); return; }
  addMsg('🧑 <em>' + prob.replace(/</g,'&lt;') + '</em>', true);
  setLoad(true);
  const btn = document.getElementById('diagBtn');
  btn.disabled = true; btn.textContent = '⏳ Analyzing...';
  fetch('/api/diagnose', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({problem:prob, vehicle:veh})
  }).then(r=>r.json()).then(data=>{
    setLoad(false); btn.disabled=false; btn.textContent='🤖 Get AI Diagnosis';
    document.getElementById('aiBadge').textContent = data.source_label || '🤖 AI';
    addMsg('<strong>🔍 AI Analysis:</strong><br><pre style="margin-top:6px">' +
      (data.response||'No response').replace(/</g,'&lt;') + '</pre>');
  }).catch(()=>{
    setLoad(false); btn.disabled=false; btn.textContent='🤖 Get AI Diagnosis';
    addMsg('❌ Connection error. Please try again.');
  });
}
function previewImage(inp) {
  if (inp.files && inp.files[0]) {
    const r = new FileReader();
    r.onload = e => {
      document.getElementById('previewImg').src = e.target.result;
      document.getElementById('imgPrev').classList.remove('hidden');
    };
    r.readAsDataURL(inp.files[0]);
  }
}
function analyzeImage() {
  const f = document.getElementById('imageInput').files[0];
  if (!f) { alert('Please select an image first!'); return; }
  addMsg('📷 <em>Uploading & analyzing vehicle image for damage...</em>', true);
  setLoad(true);
  const btn = document.getElementById('analyzeBtn');
  btn.disabled=true; btn.textContent='⏳ Analyzing image...';
  const fd = new FormData();
  fd.append('image', f);
  fetch('/api/analyze-image', {method:'POST', body:fd})
  .then(r=>r.json()).then(data=>{
    setLoad(false); btn.disabled=false; btn.textContent='🔍 Analyze Damage with AI';
    document.getElementById('aiBadge').textContent = data.source_label || '🔍 Vision AI';
    addMsg('<strong>📷 Damage Analysis:</strong><br><pre style="margin-top:6px">' +
      (data.analysis||'No analysis').replace(/</g,'&lt;') + '</pre>');
  }).catch(()=>{
    setLoad(false); btn.disabled=false; btn.textContent='🔍 Analyze Damage with AI';
    addMsg('❌ Image analysis failed. Please try again.');
  });
}
function findMechanics() {
  const lat=parseFloat(document.getElementById('uLat').value);
  const lon=parseFloat(document.getElementById('uLon').value);
  const r=parseInt(document.getElementById('sRadius').value);
  if(isNaN(lat)||isNaN(lon)){alert('Please enter your latitude and longitude!');return;}
  addMsg('📍 <em>Searching for mechanics within '+r+' km...</em>', true);
  setLoad(true);
  fetch('/api/find-mechanics',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({lat,lon,radius:r})})
  .then(r=>r.json()).then(data=>{
    setLoad(false);
    if(data.mechanics && data.mechanics.length>0){
      addMsg('<strong>✅ Found '+data.mechanics.length+' mechanic(s)!</strong> See results below.');
      showMechs(data.mechanics, lat, lon);
    } else {
      addMsg('<strong>⚠️ No mechanics found within '+r+' km.</strong><br>Click <strong>Auto-Invite</strong> to search nationwide and invite the nearest mechanics automatically!');
    }
  }).catch(()=>{setLoad(false);addMsg('❌ Search failed.');});
}
function autoInvite() {
  const lat=parseFloat(document.getElementById('uLat').value);
  const lon=parseFloat(document.getElementById('uLon').value);
  const issue=document.getElementById('problemText').value.trim()||'Vehicle breakdown';
  if(isNaN(lat)||isNaN(lon)){alert('Please enter your location first!');return;}
  addMsg('📨 <em>Searching nationwide and sending invitations to nearest mechanics...</em>', true);
  setLoad(true);
  fetch('/api/auto-invite',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({lat,lon,issue})})
  .then(r=>r.json()).then(data=>{
    setLoad(false);
    if(data.found){
      let html='<strong>📨 Invitations Sent!</strong><br>'+data.message+'<br><ul style="margin-top:8px;padding-left:4px">';
      data.invited_mechanics.forEach(m=>{
        html+='<li style="margin:4px 0">✅ <strong>'+m.name+'</strong> ('+m.expertise+') — '+m.city+' '+m.area+
              ' ('+m.distance_km+' km) | 📞 '+m.contact+'</li>';
      });
      html+='</ul>';
      addMsg(html);
      showMechs(data.invited_mechanics.map(m=>Object.assign({},m,{available:true})), lat, lon);
    } else {
      addMsg('<strong>⚠️ '+data.message+'</strong><br>📞 Emergency Hotline: <strong>01700-RESCUE</strong>');
    }
  }).catch(()=>{setLoad(false);addMsg('❌ Invitation failed.');});
}
function showMechs(mechs, uLat, uLon) {
  const box=document.getElementById('mechBox');
  const list=document.getElementById('mechList');
  box.classList.remove('hidden');
  list.innerHTML='';
  mechs.slice(0,5).forEach(m=>{
    const dist=(m.distance_km!==undefined)?m.distance_km.toFixed(1)+'km':'?km';
    const stars='⭐'.repeat(Math.round(m.rating||4));
    const avail=m.available!==false?
      '<span class="text-green-400 text-xs font-medium">● Available</span>':
      '<span class="text-red-400 text-xs font-medium">● Busy</span>';
    const div=document.createElement('div');
    div.className='bg-gray-900 border border-gray-700 rounded-lg p-4 flex gap-3 items-start fade-in';
    div.innerHTML=
      '<div class="w-10 h-10 bg-gradient-to-br from-orange-600 to-red-700 rounded-full flex items-center justify-center text-lg flex-shrink-0">🔧</div>'+
      '<div class="flex-1 min-w-0">'+
        '<div class="flex items-center gap-2 flex-wrap">'+
          '<span class="font-bold text-sm">'+(m.name||'Mechanic')+'</span>'+avail+
        '</div>'+
        '<div class="text-orange-400 text-xs mt-0.5">'+(m.expertise||'General')+'</div>'+
        '<div class="text-gray-400 text-xs mt-1">📍 '+(m.city||'')+' '+(m.area||'')+' — <strong>'+dist+'</strong></div>'+
        '<div class="text-xs mt-1">'+stars+' '+(m.rating||4).toFixed(1)+
          ' | 💰 Tk '+((m.rate_per_job||1500).toLocaleString())+'/job'+
          ' | 📞 '+(m.contact||'N/A')+'</div>'+
      '</div>'+
      '<button class="bg-orange-600 hover:bg-orange-700 px-3 py-1.5 rounded-lg text-xs font-bold flex-shrink-0 transition-colors" '+
        'onclick="inviteSpec(\''+(m.id||'')+'\',\''+(m.name||'').replace(/\'/g,"\\'")+'\',' +
        uLat+','+uLon+')">📨 Invite</button>';
    list.appendChild(div);
  });
}
function inviteSpec(id, name, lat, lon) {
  const issue=document.getElementById('problemText').value.trim()||'Vehicle breakdown';
  fetch('/api/invite-specific',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mechanic_id:id,name:name,issue:issue,lat:lat,lon:lon})})
  .then(r=>r.json()).then(data=>{
    addMsg(data.success?
      '✅ <strong>Invitation sent to '+name+'!</strong> They will contact you shortly.':
      '❌ '+data.message);
  });
}
function useGPS() {
  if(!navigator.geolocation){alert('Geolocation not supported.');return;}
  navigator.geolocation.getCurrentPosition(pos=>{
    document.getElementById('uLat').value=pos.coords.latitude.toFixed(6);
    document.getElementById('uLon').value=pos.coords.longitude.toFixed(6);
    addMsg('📡 <strong>GPS captured!</strong> Lat: '+pos.coords.latitude.toFixed(4)+', Lon: '+pos.coords.longitude.toFixed(4));
  },err=>{addMsg('❌ GPS error: '+err.message+'. Enter coordinates manually.');});
}
</script>
""")


# ── Mechanics Page ────────────────────────────────────────────────────────────
MECHANICS_TMPL = _page("""
<div class="max-w-7xl mx-auto px-6 py-8">
  <h2 class="text-3xl font-bold mb-1">🔍 Nationwide Mechanic Network</h2>
  <p class="text-gray-400 mb-8">Search our network of 38+ certified mechanics across Bangladesh</p>

  <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
    <div class="space-y-4">
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-5">
        <h3 class="font-bold text-green-400 mb-4">📍 Search by Location</h3>
        <input id="mLat" type="number" step="0.0001" placeholder="Latitude"
          class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm mb-2 focus:border-green-500 focus:outline-none placeholder-gray-600">
        <input id="mLon" type="number" step="0.0001" placeholder="Longitude"
          class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm mb-2 focus:border-green-500 focus:outline-none placeholder-gray-600">
        <select id="mRadius" class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm mb-3 focus:outline-none">
          <option value="25">Within 25 km</option>
          <option value="50" selected>Within 50 km</option>
          <option value="100">Within 100 km</option>
          <option value="200">Within 200 km</option>
          <option value="500">Nationwide (500 km)</option>
        </select>
        <button onclick="doSearch()" class="w-full bg-green-600 hover:bg-green-700 py-3 rounded-lg font-bold text-sm mb-2 transition-colors">
          🔍 Search Mechanics
        </button>
        <button onclick="gpsSearch()" class="w-full bg-gray-700 hover:bg-gray-600 py-2.5 rounded-lg text-sm transition-colors">
          📡 Use GPS Location
        </button>
      </div>

      <div class="bg-gray-800 border border-gray-700 rounded-xl p-5">
        <h3 class="font-bold text-purple-400 mb-3">🚨 Emergency Auto-Invite</h3>
        <p class="text-gray-400 text-sm mb-3">
          Far from the workshop? Our AI searches the entire country and automatically invites the 3 nearest available mechanics.
        </p>
        <input id="mIssue" placeholder="Describe your issue"
          class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm mb-3 focus:border-purple-500 focus:outline-none placeholder-gray-600">
        <button onclick="doAutoInvite()" class="w-full bg-purple-600 hover:bg-purple-700 py-3 rounded-lg font-bold text-sm transition-colors">
          📨 Auto-Invite Nearest Mechanics
        </button>
      </div>

      <div id="inviteBox" class="hidden bg-gray-800 border border-green-700 rounded-xl p-5">
        <div id="inviteContent"></div>
      </div>
    </div>

    <div class="md:col-span-2">
      <div id="mCount" class="text-gray-400 text-sm mb-4"></div>
      <div id="mResults">
        <div class="bg-gray-800 border border-gray-700 rounded-xl p-10 text-center text-gray-500">
          <div class="text-5xl mb-4">🗺️</div>
          <p class="font-medium">Enter your coordinates and click Search</p>
          <p class="text-sm mt-2">Or use Emergency Auto-Invite for nationwide dispatch</p>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
function doSearch() {
  const lat=parseFloat(document.getElementById('mLat').value);
  const lon=parseFloat(document.getElementById('mLon').value);
  const r=parseInt(document.getElementById('mRadius').value);
  if(isNaN(lat)||isNaN(lon)){alert('Please enter latitude and longitude!');return;}
  document.getElementById('mResults').innerHTML=
    '<div class="text-center py-12 text-gray-400"><div class="text-4xl spin inline-block mb-3">⚙️</div><br>Searching mechanics...</div>';
  fetch('/api/find-mechanics',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({lat,lon,radius:r})})
  .then(r=>r.json()).then(data=>{
    const ms=data.mechanics||[];
    document.getElementById('mCount').textContent=ms.length+' mechanic(s) found within '+r+' km';
    if(!ms.length){
      document.getElementById('mResults').innerHTML=
        '<div class="bg-gray-800 border border-yellow-700 rounded-xl p-8 text-center">'+
        '<div class="text-4xl mb-3">😔</div>'+
        '<p class="text-yellow-400 font-bold">No mechanics found within '+r+' km</p>'+
        '<p class="text-gray-400 text-sm mt-2">Try a larger radius or use Emergency Auto-Invite.</p></div>';
      return;
    }
    let html='';
    ms.forEach(m=>{
      const st='⭐'.repeat(Math.round(m.rating||4));
      const av=m.available!==false?
        '<span class="bg-green-900/50 text-green-400 text-xs px-2 py-0.5 rounded-full">● Available</span>':
        '<span class="bg-red-900/50 text-red-400 text-xs px-2 py-0.5 rounded-full">● Busy</span>';
      html+=
        '<div class="bg-gray-800 border border-gray-700 hover:border-green-600 rounded-xl p-5 flex gap-4 card-hover fade-in mb-3">'+
        '<div class="w-12 h-12 bg-gradient-to-br from-orange-600 to-red-700 rounded-full flex items-center justify-center text-xl flex-shrink-0">🔧</div>'+
        '<div class="flex-1">'+
          '<div class="flex items-start justify-between gap-2 flex-wrap">'+
            '<div><div class="font-bold">'+m.name+'</div>'+
            '<div class="text-orange-400 text-sm">'+m.expertise+'</div></div>'+av+
          '</div>'+
          '<div class="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-gray-400 mt-2">'+
            '<span>📍 '+m.city+', '+m.area+'</span>'+
            '<span>📏 '+m.distance_km.toFixed(1)+' km away</span>'+
            '<span>'+st+' '+(m.rating||4).toFixed(1)+' rating</span>'+
            '<span>💰 Tk '+(m.rate_per_job||1500).toLocaleString()+'/job</span>'+
            '<span>🛠️ '+m.years_experience+' yrs exp</span>'+
            '<span>📞 '+m.contact+'</span>'+
          '</div>'+
        '</div>'+
        '<button onclick="qInvite(\''+m.id+'\',\''+m.name.replace(/\'/g,"\\'")+'\','+lat+','+lon+')" '+
          'class="bg-orange-600 hover:bg-orange-700 px-4 py-2 rounded-lg text-sm font-bold self-center transition-colors flex-shrink-0">📨 Invite</button>'+
        '</div>';
    });
    document.getElementById('mResults').innerHTML=html;
  }).catch(()=>{document.getElementById('mResults').innerHTML='<div class="text-red-400 p-4">Search failed.</div>';});
}
function doAutoInvite() {
  const lat=parseFloat(document.getElementById('mLat').value);
  const lon=parseFloat(document.getElementById('mLon').value);
  const issue=document.getElementById('mIssue').value.trim()||'Vehicle breakdown';
  if(isNaN(lat)||isNaN(lon)){alert('Please enter location first!');return;}
  document.getElementById('inviteBox').classList.add('hidden');
  fetch('/api/auto-invite',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({lat,lon,issue})})
  .then(r=>r.json()).then(data=>{
    const box=document.getElementById('inviteBox');
    const c=document.getElementById('inviteContent');
    box.classList.remove('hidden');
    if(data.found){
      let h='<h4 class="font-bold text-green-400 mb-2">✅ Invitations Sent!</h4>'+
        '<p class="text-sm text-gray-300 mb-3">'+data.message+'</p>';
      data.invited_mechanics.forEach(m=>{
        h+='<div class="bg-gray-900 rounded-lg p-3 mb-2 text-sm">'+
          '<strong>'+m.name+'</strong> — '+m.expertise+'<br>'+
          '<span class="text-gray-400">📍 '+m.city+' '+m.area+
          ' ('+m.distance_km.toFixed(1)+' km) | 📞 '+m.contact+'</span></div>';
      });
      c.innerHTML=h;
    } else {
      c.innerHTML='<h4 class="font-bold text-yellow-400 mb-2">⚠️ No Mechanics Found</h4>'+
        '<p class="text-sm text-gray-300">'+data.message+'</p>'+
        '<p class="text-orange-400 mt-3 font-bold">📞 Emergency: 01700-RESCUE</p>';
    }
  });
}
function qInvite(id,name,lat,lon){
  const issue=document.getElementById('mIssue').value.trim()||'Vehicle breakdown';
  fetch('/api/invite-specific',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mechanic_id:id,name:name,issue:issue,lat:lat,lon:lon})})
  .then(r=>r.json()).then(d=>{alert(d.success?'✅ Invitation sent to '+name+'!':'❌ '+d.message);});
}
function gpsSearch(){
  if(!navigator.geolocation){alert('Not supported.');return;}
  navigator.geolocation.getCurrentPosition(p=>{
    document.getElementById('mLat').value=p.coords.latitude.toFixed(6);
    document.getElementById('mLon').value=p.coords.longitude.toFixed(6);
    doSearch();
  },e=>{alert('GPS error: '+e.message);});
}
</script>
""")


# ── Customer — Unauthenticated ─────────────────────────────────────────────────
CUSTOMER_ANON_TMPL = _page("""
<div class="max-w-md mx-auto px-6 py-12">
  <div class="text-center mb-8">
    <div class="text-5xl mb-3">👤</div>
    <h2 class="text-3xl font-bold">Customer Portal</h2>
    <p class="text-gray-400 mt-2">Login or register to request services</p>
  </div>

  {% if flash_msg %}
  <div class="bg-red-900/50 border border-red-700 rounded-lg p-3 mb-5 text-sm text-red-300">⚠️ {{ flash_msg }}</div>
  {% endif %}
  {% if success_msg %}
  <div class="bg-green-900/50 border border-green-700 rounded-lg p-3 mb-5 text-sm text-green-300">✅ {{ success_msg }}</div>
  {% endif %}

  <div class="flex mb-5 bg-gray-800 rounded-lg p-1">
    <button id="tabL" onclick="showTab('login')" class="flex-1 py-2 rounded-md text-sm font-medium bg-orange-600 text-white transition-colors">Login</button>
    <button id="tabR" onclick="showTab('register')" class="flex-1 py-2 rounded-md text-sm font-medium text-gray-400 hover:text-white transition-colors">Register</button>
  </div>

  <div id="loginF" class="bg-gray-800 border border-gray-700 rounded-xl p-6">
    <form method="POST" action="/customer/login" class="space-y-3">
      <input name="phone" type="tel" placeholder="📱 Phone Number" required
        class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:border-orange-500 focus:outline-none placeholder-gray-600">
      <input name="password" type="password" placeholder="🔒 Password" required
        class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:border-orange-500 focus:outline-none placeholder-gray-600">
      <button type="submit" class="w-full bg-orange-600 hover:bg-orange-700 py-3 rounded-lg font-bold transition-colors">🔓 Login</button>
    </form>
  </div>

  <div id="registerF" class="hidden bg-gray-800 border border-gray-700 rounded-xl p-6">
    <form method="POST" action="/customer/register" class="space-y-3">
      <input name="name" placeholder="👤 Full Name" required
        class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:border-green-500 focus:outline-none placeholder-gray-600">
      <input name="phone" type="tel" placeholder="📱 Phone Number" required
        class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:border-green-500 focus:outline-none placeholder-gray-600">
      <input name="address" placeholder="🏠 Address (optional)"
        class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:border-green-500 focus:outline-none placeholder-gray-600">
      <input name="password" type="password" placeholder="🔒 Create Password" required
        class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:border-green-500 focus:outline-none placeholder-gray-600">
      <div class="border-t border-gray-700 pt-3">
        <p class="text-gray-500 text-xs mb-2">Vehicle Details (optional — add later):</p>
        <input name="v_reg" placeholder="🚗 Registration No."
          class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm mb-2 focus:outline-none placeholder-gray-600">
        <div class="grid grid-cols-2 gap-2">
          <input name="v_brand" placeholder="Brand (Toyota)" class="bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:outline-none placeholder-gray-600">
          <input name="v_model" placeholder="Model (Corolla)" class="bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:outline-none placeholder-gray-600">
        </div>
        <div class="grid grid-cols-2 gap-2 mt-2">
          <input name="v_colour" placeholder="Color" class="bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:outline-none placeholder-gray-600">
          <input name="v_year" type="number" placeholder="Year" class="bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:outline-none placeholder-gray-600">
        </div>
      </div>
      <button type="submit" class="w-full bg-green-600 hover:bg-green-700 py-3 rounded-lg font-bold transition-colors">✅ Create Account</button>
    </form>
  </div>
</div>

<script>
function showTab(t) {
  document.getElementById('loginF').classList.toggle('hidden', t!=='login');
  document.getElementById('registerF').classList.toggle('hidden', t!=='register');
  document.getElementById('tabL').className='flex-1 py-2 rounded-md text-sm font-medium transition-colors '+
    (t==='login'?'bg-orange-600 text-white':'text-gray-400 hover:text-white');
  document.getElementById('tabR').className='flex-1 py-2 rounded-md text-sm font-medium transition-colors '+
    (t==='register'?'bg-green-600 text-white':'text-gray-400 hover:text-white');
}
</script>
""")


# ── Customer Dashboard ────────────────────────────────────────────────────────
DASH_TMPL = _page("""
<div class="max-w-4xl mx-auto px-6 py-8">
  <div class="flex items-center justify-between mb-8">
    <div>
      <h2 class="text-2xl font-bold">Welcome, {{ cust_name }}! 👋</h2>
      <p class="text-gray-400 text-sm mt-1">📱 {{ cust_phone }}</p>
    </div>
    <a href="/customer/logout" class="bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded-lg text-sm transition-colors">
      🚪 Logout
    </a>
  </div>

  {% if flash_msg %}
  <div class="bg-red-900/50 border border-red-700 rounded-lg p-3 mb-5 text-sm text-red-300">⚠️ {{ flash_msg }}</div>
  {% endif %}
  {% if success_msg %}
  <div class="bg-green-900/50 border border-green-700 rounded-lg p-3 mb-5 text-sm text-green-300">✅ {{ success_msg }}</div>
  {% endif %}

  <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
    <a href="/service/request" class="bg-orange-600 hover:bg-orange-700 rounded-xl p-5 text-center transition-all card-hover">
      <div class="text-3xl mb-2">🛠️</div>
      <div class="font-bold">Request Service</div>
      <div class="text-orange-200 text-xs mt-1">Order mechanic + parts</div>
    </a>
    <a href="/ai" class="bg-blue-700 hover:bg-blue-600 rounded-xl p-5 text-center transition-all card-hover">
      <div class="text-3xl mb-2">🤖</div>
      <div class="font-bold">AI Diagnosis</div>
      <div class="text-blue-200 text-xs mt-1">Describe your problem</div>
    </a>
    <a href="/mechanics" class="bg-green-700 hover:bg-green-600 rounded-xl p-5 text-center transition-all card-hover">
      <div class="text-3xl mb-2">🔍</div>
      <div class="font-bold">Find Mechanic</div>
      <div class="text-green-200 text-xs mt-1">Nationwide search</div>
    </a>
  </div>

  <!-- Vehicle Card -->
  <div class="bg-gray-800 border border-gray-700 rounded-xl p-6 mb-6">
    <div class="flex items-center justify-between mb-4">
      <h3 class="font-bold text-lg">🚗 My Vehicle</h3>
      {% if not has_vehicle %}
      <a href="/customer/add-vehicle" class="bg-orange-600 hover:bg-orange-700 px-4 py-1.5 rounded-lg text-sm transition-colors">+ Add Vehicle</a>
      {% endif %}
    </div>
    {% if has_vehicle %}
    <div class="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
      <div><span class="text-gray-400">Registration</span><div class="font-mono font-bold mt-0.5">{{ v_reg }}</div></div>
      <div><span class="text-gray-400">Brand</span><div class="font-bold mt-0.5">{{ v_brand }}</div></div>
      <div><span class="text-gray-400">Model</span><div class="font-bold mt-0.5">{{ v_model }}</div></div>
      <div><span class="text-gray-400">Color</span><div class="font-bold mt-0.5">{{ v_colour }}</div></div>
      <div><span class="text-gray-400">Year</span><div class="font-bold mt-0.5">{{ v_year }}</div></div>
    </div>
    {% else %}
    <div class="text-center py-6 text-gray-500">
      <div class="text-4xl mb-2">🚗</div>
      <p>No vehicle registered yet.</p>
      <a href="/customer/add-vehicle" class="text-orange-400 hover:underline text-sm mt-1 inline-block">Add your vehicle →</a>
    </div>
    {% endif %}
  </div>

  <!-- Service Requests -->
  <div class="bg-gray-800 border border-gray-700 rounded-xl p-6">
    <h3 class="font-bold text-lg mb-4">📋 My Service Requests</h3>
    {% if requests %}
    <div class="space-y-3">
      {% for r in requests %}
      <div class="bg-gray-900 border border-gray-700 rounded-lg p-4 text-sm">
        <div class="flex items-center justify-between mb-1">
          <span class="font-bold text-orange-400">Request #{{ r.id }}</span>
          <span class="{% if r.paid %}bg-green-900/50 text-green-400{% else %}bg-yellow-900/50 text-yellow-400{% endif %} text-xs px-2 py-0.5 rounded-full">
            {% if r.paid %}✅ Paid via {{ r.payment_method }}{% else %}⏳ Payment Pending{% endif %}
          </span>
        </div>
        <div class="text-gray-300">Issue: {{ r.issue }}</div>
        <div class="text-gray-400 text-xs mt-1">Total: <strong>Tk {{ "%.2f"|format(r.total_amount) }}</strong>
          | Part: {{ r.chosen_part_name }} | Roadside: {{ "Yes" if r.roadside else "No" }}</div>
      </div>
      {% endfor %}
    </div>
    {% else %}
    <div class="text-center py-6 text-gray-500">
      <div class="text-3xl mb-2">📋</div>
      <p>No service requests yet.</p>
      <a href="/service/request" class="text-orange-400 hover:underline text-sm mt-1 inline-block">Create your first request →</a>
    </div>
    {% endif %}
  </div>
</div>
""")


# ── Add Vehicle ───────────────────────────────────────────────────────────────
ADD_VEH_TMPL = _page("""
<div class="max-w-md mx-auto px-6 py-10">
  <h2 class="text-2xl font-bold mb-6">🚗 Add Your Vehicle</h2>
  <div class="bg-gray-800 border border-gray-700 rounded-xl p-6">
    <form method="POST" action="/customer/add-vehicle" class="space-y-3">
      <input name="v_reg" placeholder="Registration No. (e.g. DHK-12-3456)" required
        class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:border-orange-500 focus:outline-none placeholder-gray-600">
      <div class="grid grid-cols-2 gap-2">
        <input name="v_brand" placeholder="Brand (Toyota)" required
          class="bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:border-orange-500 focus:outline-none placeholder-gray-600">
        <input name="v_model" placeholder="Model (Corolla)" required
          class="bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:border-orange-500 focus:outline-none placeholder-gray-600">
      </div>
      <div class="grid grid-cols-2 gap-2">
        <input name="v_colour" placeholder="Color (White)" required
          class="bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:border-orange-500 focus:outline-none placeholder-gray-600">
        <input name="v_year" type="number" placeholder="Year (2019)" min="1990" max="2025"
          class="bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:border-orange-500 focus:outline-none placeholder-gray-600">
      </div>
      <button type="submit" class="w-full bg-orange-600 hover:bg-orange-700 py-3 rounded-lg font-bold transition-colors">✅ Save Vehicle</button>
    </form>
  </div>
  <a href="/customer/dashboard" class="text-gray-400 hover:text-white text-sm mt-4 inline-block">← Back to Dashboard</a>
</div>
""")


# ── Service Request ───────────────────────────────────────────────────────────
SERVICE_TMPL = _page("""
<div class="max-w-2xl mx-auto px-6 py-8">
  <h2 class="text-2xl font-bold mb-1">🛠️ Request Service</h2>
  <p class="text-gray-400 text-sm mb-6">Vehicle: <strong>{{ veh_str }}</strong></p>

  {% if flash_msg %}
  <div class="bg-red-900/50 border border-red-700 rounded-lg p-3 mb-5 text-sm text-red-300">⚠️ {{ flash_msg }}</div>
  {% endif %}

  <form method="POST" action="/service/request" class="space-y-5">
    <!-- Issue -->
    <div class="bg-gray-800 border border-gray-700 rounded-xl p-5">
      <label class="block text-orange-400 font-bold mb-2">💬 Describe the Issue</label>
      <textarea name="issue" rows="3" required placeholder="e.g., Engine won't start, tire puncture, ran out of fuel..."
        class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm resize-none focus:border-orange-500 focus:outline-none placeholder-gray-600"></textarea>
      <button type="button" onclick="getAISuggestions()"
        class="mt-2 text-xs bg-gray-700 hover:bg-gray-600 px-3 py-1.5 rounded-lg transition-colors">
        🤖 Get AI Suggestions
      </button>
      <div id="aiSug" class="hidden mt-3 bg-gray-900 border border-gray-600 rounded-lg p-3 text-xs text-gray-300"></div>
    </div>

    <!-- Part -->
    <div class="bg-gray-800 border border-gray-700 rounded-xl p-5">
      <label class="block text-orange-400 font-bold mb-3">🔩 Select Part Needed</label>
      <div class="space-y-2 max-h-56 overflow-y-auto">
        {% for p in parts %}
        <label class="flex items-center gap-3 bg-gray-900 border border-gray-700 hover:border-orange-500 rounded-lg p-3 cursor-pointer transition-colors">
          <input type="radio" name="part_code" value="{{ p.code }}" required class="accent-orange-500">
          <div class="flex-1 text-sm">
            <span class="font-medium">{{ p.name }}</span>
            <span class="text-gray-500 text-xs ml-2">{{ p.code }}</span>
          </div>
          <span class="text-orange-400 text-sm font-bold">Tk {{ "%.0f"|format(p.price) }}</span>
        </label>
        {% endfor %}
      </div>
    </div>

    <!-- Mechanic -->
    <div class="bg-gray-800 border border-gray-700 rounded-xl p-5">
      <label class="block text-orange-400 font-bold mb-3">🔧 Select Mechanic</label>
      <div class="space-y-2 max-h-56 overflow-y-auto">
        {% for m in mechanics %}
        <label class="flex items-center gap-3 bg-gray-900 border border-gray-700 hover:border-orange-500 rounded-lg p-3 cursor-pointer transition-colors {% if not m.available %}opacity-50{% endif %}">
          <input type="radio" name="mech_idx" value="{{ loop.index0 }}" required {% if not m.available %}disabled{% endif %} class="accent-orange-500">
          <div class="flex-1 text-sm">
            <div class="font-medium">{{ m.name }} <span class="text-xs text-orange-400">{{ m.expertise }}</span></div>
            <div class="text-gray-500 text-xs">{{ m.code }} | {% if m.available %}Available{% else %}Busy{% endif %}</div>
          </div>
          <span class="text-orange-400 text-sm font-bold">Tk {{ "%.0f"|format(m.rate_per_job) }}</span>
        </label>
        {% endfor %}
      </div>
    </div>

    <!-- Roadside -->
    <div class="bg-gray-800 border border-gray-700 rounded-xl p-5">
      <label class="block text-orange-400 font-bold mb-3">📍 Roadside Help?</label>
      <div class="flex gap-4">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="radio" name="roadside" value="1" onchange="toggleLoc(true)" class="accent-orange-500"> Yes (+Tk 100)
        </label>
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="radio" name="roadside" value="0" onchange="toggleLoc(false)" checked class="accent-orange-500"> No (Workshop pickup)
        </label>
      </div>
      <div id="locDiv" class="hidden mt-4 space-y-2">
        <p class="text-gray-400 text-sm">Select your current area:</p>
        <select name="loc_idx" class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:outline-none">
          {% for loc in locations %}
          <option value="{{ loop.index0 }}">{{ loc.area_name }} ({{ loc.lat }}, {{ loc.lon }})</option>
          {% endfor %}
          {% if not locations %}
          <option value="-1">No location list loaded</option>
          {% endif %}
        </select>
      </div>
    </div>

    <!-- Payment -->
    <div class="bg-gray-800 border border-gray-700 rounded-xl p-5">
      <label class="block text-orange-400 font-bold mb-3">💳 Payment Method</label>
      <div class="grid grid-cols-2 gap-2">
        <label class="flex items-center gap-2 bg-gray-900 border border-gray-700 rounded-lg p-3 cursor-pointer hover:border-green-500 transition-colors">
          <input type="radio" name="payment" value="bKash" required class="accent-green-500">
          <span class="text-sm">💚 bKash</span>
        </label>
        <label class="flex items-center gap-2 bg-gray-900 border border-gray-700 rounded-lg p-3 cursor-pointer hover:border-orange-500 transition-colors">
          <input type="radio" name="payment" value="Nagad" class="accent-orange-500">
          <span class="text-sm">🟠 Nagad</span>
        </label>
        <label class="flex items-center gap-2 bg-gray-900 border border-gray-700 rounded-lg p-3 cursor-pointer hover:border-blue-500 transition-colors">
          <input type="radio" name="payment" value="Debit Card" class="accent-blue-500">
          <span class="text-sm">💳 Debit Card</span>
        </label>
        <label class="flex items-center gap-2 bg-gray-900 border border-gray-700 rounded-lg p-3 cursor-pointer hover:border-purple-500 transition-colors">
          <input type="radio" name="payment" value="Credit Card" class="accent-purple-500">
          <span class="text-sm">💳 Credit Card</span>
        </label>
      </div>
    </div>

    <button type="submit" class="w-full bg-orange-600 hover:bg-orange-700 py-4 rounded-xl font-bold text-lg transition-all transform hover:scale-[1.01] shadow-lg">
      ✅ Confirm Service Request
    </button>
  </form>
</div>

<script>
function toggleLoc(show) {
  document.getElementById('locDiv').classList.toggle('hidden', !show);
}
function getAISuggestions() {
  const issue = document.querySelector('[name=issue]').value.trim();
  if (!issue) { alert('Please describe the issue first!'); return; }
  const d = document.getElementById('aiSug');
  d.classList.remove('hidden');
  d.textContent = '🤖 Analyzing...';
  fetch('/api/diagnose', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({problem: issue, vehicle: '{{ veh_str }}'})})
  .then(r=>r.json()).then(data=>{
    d.innerHTML = '<strong class="text-orange-400">AI Suggestions:</strong><pre style="margin-top:4px;font-size:11px">' +
      (data.response||'').replace(/</g,'&lt;') + '</pre>';
  }).catch(()=>{ d.textContent = '❌ Could not get AI suggestions.'; });
}
</script>
""")


# ── Confirmation Page ─────────────────────────────────────────────────────────
CONFIRM_TMPL = _page("""
<div class="max-w-lg mx-auto px-6 py-12 text-center">
  <div class="text-6xl mb-4">✅</div>
  <h2 class="text-3xl font-bold text-green-400 mb-2">Service Requested!</h2>
  <p class="text-gray-400 mb-8">Your service request has been placed successfully.</p>

  <div class="bg-gray-800 border border-gray-700 rounded-xl p-6 text-left space-y-3 mb-8">
    <div class="flex justify-between text-sm"><span class="text-gray-400">Request ID</span><span class="font-bold">#{{ req_id }}</span></div>
    <div class="flex justify-between text-sm"><span class="text-gray-400">Issue</span><span>{{ issue }}</span></div>
    <div class="flex justify-between text-sm"><span class="text-gray-400">Part</span><span>{{ part_name }}</span></div>
    <div class="flex justify-between text-sm"><span class="text-gray-400">Mechanic</span><span>{{ mech_name }}</span></div>
    <div class="flex justify-between text-sm"><span class="text-gray-400">Roadside</span><span>{{ roadside }}</span></div>
    <div class="border-t border-gray-700 pt-3 flex justify-between font-bold"><span>Total</span><span class="text-orange-400">Tk {{ total }}</span></div>
    <div class="flex justify-between text-sm"><span class="text-gray-400">Payment</span><span class="text-green-400">✅ {{ payment }}</span></div>
  </div>

  {% if nearby_mechs %}
  <div class="bg-blue-900/30 border border-blue-700 rounded-xl p-5 text-left mb-6">
    <p class="text-blue-300 font-bold mb-2">📨 You are far from our workshop!</p>
    <p class="text-gray-300 text-sm mb-3">We found and notified {{ nearby_mechs|length }} mechanic(s) near you:</p>
    {% for m in nearby_mechs %}
    <div class="text-sm text-gray-300 mb-1">✅ <strong>{{ m.name }}</strong> ({{ m.expertise }}) — {{ m.distance_km }} km away | 📞 {{ m.contact }}</div>
    {% endfor %}
  </div>
  {% endif %}

  <div class="flex gap-3 justify-center">
    <a href="/customer/dashboard" class="bg-orange-600 hover:bg-orange-700 px-6 py-3 rounded-lg font-bold transition-colors">← My Dashboard</a>
    <a href="/ai" class="bg-gray-700 hover:bg-gray-600 px-6 py-3 rounded-lg font-bold transition-colors">🤖 AI Assistant</a>
  </div>
</div>
""")


# ── Admin Panel ───────────────────────────────────────────────────────────────
ADMIN_LOGIN_TMPL = _page("""
<div class="max-w-sm mx-auto px-6 py-16">
  <div class="text-center mb-8">
    <div class="text-5xl mb-3">🛡️</div>
    <h2 class="text-2xl font-bold">Admin Login</h2>
  </div>
  {% if error %}
  <div class="bg-red-900/50 border border-red-700 rounded-lg p-3 mb-4 text-sm text-red-300">❌ {{ error }}</div>
  {% endif %}
  <div class="bg-gray-800 border border-gray-700 rounded-xl p-6">
    <form method="POST" action="/admin/login" class="space-y-3">
      <input name="username" placeholder="👤 Username" required
        class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:border-orange-500 focus:outline-none placeholder-gray-600">
      <input name="password" type="password" placeholder="🔒 Password" required
        class="w-full bg-gray-900 border border-gray-600 rounded-lg p-3 text-sm focus:border-orange-500 focus:outline-none placeholder-gray-600">
      <button type="submit" class="w-full bg-orange-600 hover:bg-orange-700 py-3 rounded-lg font-bold transition-colors">🔓 Login as Admin</button>
    </form>
    <p class="text-gray-600 text-xs text-center mt-4">Hint: Pinkman / youbettercallsaul</p>
  </div>
</div>
""")

ADMIN_DASH_TMPL = _page("""
<div class="max-w-7xl mx-auto px-6 py-8">
  <div class="flex items-center justify-between mb-8">
    <h2 class="text-2xl font-bold">🛡️ Admin Dashboard</h2>
    <div class="flex gap-3">
      <a href="/export/bills" class="bg-green-700 hover:bg-green-600 px-4 py-2 rounded-lg text-sm transition-colors">📊 Export Bills CSV</a>
      <a href="/admin/logout" class="bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded-lg text-sm transition-colors">🚪 Logout</a>
    </div>
  </div>

  <!-- Stats -->
  <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
    <div class="bg-gray-800 border border-gray-700 rounded-xl p-4 text-center">
      <div class="text-2xl font-bold text-orange-400">{{ total_customers }}</div><div class="text-gray-400 text-sm">Customers</div>
    </div>
    <div class="bg-gray-800 border border-gray-700 rounded-xl p-4 text-center">
      <div class="text-2xl font-bold text-blue-400">{{ total_requests }}</div><div class="text-gray-400 text-sm">Requests</div>
    </div>
    <div class="bg-gray-800 border border-gray-700 rounded-xl p-4 text-center">
      <div class="text-2xl font-bold text-green-400">{{ paid_requests }}</div><div class="text-gray-400 text-sm">Paid</div>
    </div>
    <div class="bg-gray-800 border border-gray-700 rounded-xl p-4 text-center">
      <div class="text-2xl font-bold text-purple-400">Tk {{ total_revenue }}</div><div class="text-gray-400 text-sm">Revenue</div>
    </div>
  </div>

  <!-- Requests Table -->
  <div class="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden mb-8">
    <div class="p-4 border-b border-gray-700"><h3 class="font-bold">📋 All Service Requests</h3></div>
    {% if requests %}
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead class="bg-gray-700">
          <tr>
            <th class="text-left p-3 text-gray-300">ID</th>
            <th class="text-left p-3 text-gray-300">Customer</th>
            <th class="text-left p-3 text-gray-300">Issue</th>
            <th class="text-left p-3 text-gray-300">Part</th>
            <th class="text-left p-3 text-gray-300">Mechanic</th>
            <th class="text-left p-3 text-gray-300">Total</th>
            <th class="text-left p-3 text-gray-300">Status</th>
            <th class="text-left p-3 text-gray-300">Action</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-700">
          {% for r in requests %}
          <tr class="hover:bg-gray-750 transition-colors">
            <td class="p-3 font-mono text-orange-400">#{{ r.id }}</td>
            <td class="p-3">{{ r.cust_name }}<br><span class="text-gray-500 text-xs">{{ r.cust_phone }}</span></td>
            <td class="p-3 text-gray-300 max-w-xs truncate">{{ r.issue }}</td>
            <td class="p-3 text-gray-300">{{ r.part_name }}</td>
            <td class="p-3 text-gray-300">{{ r.mech_name }}</td>
            <td class="p-3 font-bold text-green-400">Tk {{ "%.0f"|format(r.total) }}</td>
            <td class="p-3">
              {% if r.paid %}
              <span class="bg-green-900/50 text-green-400 text-xs px-2 py-0.5 rounded-full">✅ {{ r.payment }}</span>
              {% else %}
              <span class="bg-yellow-900/50 text-yellow-400 text-xs px-2 py-0.5 rounded-full">⏳ Pending</span>
              {% endif %}
            </td>
            <td class="p-3">
              {% if not r.paid %}
              <form method="POST" action="/admin/mark-paid" style="display:inline">
                <input type="hidden" name="req_id" value="{{ r.id }}">
                <button type="submit" class="bg-green-700 hover:bg-green-600 text-xs px-2 py-1 rounded transition-colors">Mark Paid</button>
              </form>
              {% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <div class="p-10 text-center text-gray-500">No service requests yet.</div>
    {% endif %}
  </div>

  <!-- Invitations Log -->
  <div class="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
    <div class="p-4 border-b border-gray-700"><h3 class="font-bold">📨 Mechanic Invitation Log</h3></div>
    {% if invitations %}
    <div class="divide-y divide-gray-700">
      {% for inv in invitations %}
      <div class="p-4 text-sm flex items-start gap-4">
        <div class="w-8 h-8 bg-purple-700 rounded-full flex items-center justify-center flex-shrink-0 text-sm">📨</div>
        <div class="flex-1">
          <div><strong>{{ inv.name }}</strong> ({{ inv.expertise }}) — {{ inv.city }}</div>
          <div class="text-gray-400 text-xs mt-0.5">Issue: {{ inv.issue }} | For: {{ inv.customer_name }} | 📞 {{ inv.contact }}</div>
          <div class="text-gray-500 text-xs mt-0.5">{{ inv.timestamp }}</div>
        </div>
        <span class="text-green-400 text-xs">{{ inv.status }}</span>
      </div>
      {% endfor %}
    </div>
    {% else %}
    <div class="p-8 text-center text-gray-500">No invitations sent yet.</div>
    {% endif %}
  </div>
</div>
""")


# ═════════════════════════════════════════════════════════════════════════════
#  SYSTEM MANAGER
# ═════════════════════════════════════════════════════════════════════════════

class SystemManager:
    ADMIN_USER = "Pinkman"
    ADMIN_HASH = simple_hash("youbettercallsaul")

    def __init__(self):
        print("\n" + "=" * 70)
        print("   🚗  RoadRescue — Workshop Management & Breakdown Assistance System")
        print(f"        Version {VERSION}")
        print("=" * 70)

        self.customers:  List[Customer]       = []
        self.mechanics:  List[Mechanic]       = []
        self.parts:      List[Part]           = []
        self.requests:   List[ServiceRequest] = []
        self._next_req_id = 1

        self._data_mgr   = SystemDataManager()
        self.ai          = GeminiAIAssistant()
        self.network     = NationwideMechanicNetwork("nationwide_mechanics.json")

        self._dhaka_db   = DhakaLocationDatabase()
        self._locations: List[NamedLocation] = []

        self.app = Flask(__name__)
        self.app.secret_key = SECRET_KEY

        self._load_parts()
        self._load_mechanics()
        self._load_locations()
        self._setup_routes()

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_parts(self):
        if not self._data_mgr.load_parts_file("parts.txt"):
            print("  [Parts] parts.txt not found — adding fallback parts.")
            for p in [
                Part("P001", "Engine Oil", 1200.0),
                Part("P002", "Brake Pad Set", 1800.0),
                Part("P003", "Battery 12V", 5200.0),
                Part("P004", "Spark Plug Set", 900.0),
                Part("P005", "Fuel Pump", 8500.0),
                Part("P006", "Air Filter", 600.0),
                Part("P007", "Tire (Standard)", 4500.0),
                Part("P008", "Shock Absorber", 2800.0),
            ]:
                self._data_mgr.add_part_fallback(p)
        self.parts = self._data_mgr.get_all_parts()
        print(f"  [Parts] {len(self.parts)} part(s) loaded.")

    def _load_mechanics(self):
        self.mechanics = [
            Mechanic("M001", "Rahim Uddin",     "Engine Specialist",              2000.0, location=Location(23.8103, 90.4125)),
            Mechanic("M002", "Shaon Ahmed",     "Engine Specialist",              1800.0, location=Location(23.8103, 90.4125)),
            Mechanic("M003", "Ahmed Efty",      "Engine Specialist",              1800.0, location=Location(23.8103, 90.4125)),
            Mechanic("M004", "Rakib Hasan",     "Engine Specialist (Bike)",       1800.0, location=Location(23.8103, 90.4125)),
            Mechanic("M005", "Jamal Uddin",     "Engine Specialist (Bike)",       1500.0, location=Location(23.8103, 90.4125)),
            Mechanic("M006", "Karim Hossain",   "Brake Expert",                   1800.0, location=Location(23.8103, 90.4125)),
            Mechanic("M007", "Jafor Hossain",   "Brake Expert (Bike)",            1500.0, location=Location(23.8103, 90.4125)),
            Mechanic("M008", "Sajid Khan",      "Electrical Specialist",          2500.0, location=Location(23.8103, 90.4125)),
            Mechanic("M009", "Efat Hasan",      "Electrical Specialist",          2200.0, location=Location(23.8103, 90.4125)),
            Mechanic("M010", "Tamim Islam",     "Electrical Specialist (Bike)",   2200.0, location=Location(23.8103, 90.4125)),
            Mechanic("M011", "Sabbir Hasan",    "General Mechanic Expert",        1500.0, location=Location(23.8103, 90.4125)),
            Mechanic("M012", "Rafiq Ullah",     "General Mechanic Expert (Bike)", 1500.0, location=Location(23.8103, 90.4125)),
            Mechanic("M013", "Ahmed Samir",     "Suspension & Steering Expert",   1800.0, location=Location(23.8103, 90.4125)),
        ]
        print(f"  [Workshop] {len(self.mechanics)} mechanic(s) registered.")

    def _load_locations(self):
        if self._dhaka_db.load("locations.txt"):
            self._locations = self._dhaka_db.locations
            print(f"  [Locations] {len(self._locations)} location(s) loaded from locations.txt.")
        else:
            print("  [Locations] locations.txt unavailable — manual coordinates only.")

    # ── Flask routes ──────────────────────────────────────────────────────────

    def _setup_routes(self):
        app = self.app

        # ── Home ──
        @app.route("/")
        def home():
            return render_template_string(HOME_TMPL, page_title="Home")

        # ── AI Pages ──
        @app.route("/ai")
        def ai_page():
            return render_template_string(AI_TMPL,
                page_title="AI Assistant",
                ai_status=self.ai.status_label,
                ai_badge=self.ai.badge)

        # ── API: Diagnose ──
        @app.route("/api/diagnose", methods=["POST"])
        def api_diagnose():
            data    = request.get_json(force=True, silent=True) or {}
            problem = data.get("problem", "").strip()
            vehicle = data.get("vehicle", "").strip()
            if not problem:
                return jsonify({"success": False, "response": "Please provide a problem description."}), 400
            result = self.ai.diagnose_problem(problem, vehicle)
            return jsonify(result)

        # ── API: Analyze Image ──
        @app.route("/api/analyze-image", methods=["POST"])
        def api_analyze_image():
            if "image" not in request.files:
                return jsonify({"success": False, "analysis": "No image provided."}), 400
            f = request.files["image"]
            image_bytes = f.read()
            mime = f.content_type or "image/jpeg"
            result = self.ai.analyze_vehicle_image(image_bytes, mime)
            return jsonify(result)

        # ── API: Find Mechanics ──
        @app.route("/api/find-mechanics", methods=["POST"])
        def api_find_mechanics():
            data   = request.get_json(force=True, silent=True) or {}
            lat    = float(data.get("lat", 0))
            lon    = float(data.get("lon", 0))
            radius = float(data.get("radius", 50))
            found  = self.network.find_nearby(lat, lon, radius)
            return jsonify({"mechanics": found, "count": len(found)})

        # ── API: Auto-Invite ──
        @app.route("/api/auto-invite", methods=["POST"])
        def api_auto_invite():
            data   = request.get_json(force=True, silent=True) or {}
            lat    = float(data.get("lat", 0))
            lon    = float(data.get("lon", 0))
            issue  = data.get("issue", "Vehicle breakdown")
            cname  = "Customer"
            if "customer_idx" in session:
                idx = session["customer_idx"]
                if 0 <= idx < len(self.customers):
                    cname = self.customers[idx].get_name()
            result = self.network.auto_search_and_invite(lat, lon, issue, cname)
            return jsonify(result)

        # ── API: Invite Specific ──
        @app.route("/api/invite-specific", methods=["POST"])
        def api_invite_specific():
            data   = request.get_json(force=True, silent=True) or {}
            mid    = data.get("mechanic_id", "")
            issue  = data.get("issue", "Vehicle breakdown")
            lat    = float(data.get("lat", 0))
            lon    = float(data.get("lon", 0))
            cname  = "Customer"
            if "customer_idx" in session:
                idx = session["customer_idx"]
                if 0 <= idx < len(self.customers):
                    cname = self.customers[idx].get_name()
            result = self.network.invite_specific(mid, issue, lat, lon, cname)
            return jsonify(result)

        # ── Mechanics Page ──
        @app.route("/mechanics")
        def mechanics_page():
            return render_template_string(MECHANICS_TMPL, page_title="Find Mechanic")

        # ── Customer ──
        @app.route("/customer")
        def customer_page():
            if "customer_idx" in session:
                return redirect(url_for("customer_dashboard"))
            return render_template_string(CUSTOMER_ANON_TMPL,
                page_title="Customer Portal", flash_msg="", success_msg="")

        @app.route("/customer/register", methods=["POST"])
        def customer_register():
            name   = request.form.get("name", "").strip()
            phone  = request.form.get("phone", "").strip()
            pw     = request.form.get("password", "").strip()
            addr   = request.form.get("address", "").strip()
            if not name or not phone or not pw:
                return render_template_string(CUSTOMER_ANON_TMPL,
                    page_title="Customer Portal", flash_msg="Name, phone and password are required.", success_msg="")
            for c in self.customers:
                if c.phone == phone:
                    return render_template_string(CUSTOMER_ANON_TMPL,
                        page_title="Customer Portal", flash_msg="Phone already registered. Please login.", success_msg="")
            cust         = Customer(name, phone, pw)
            cust.id      = len(self.customers) + 1
            cust.address = addr
            # Optional vehicle
            v_reg = request.form.get("v_reg", "").strip()
            v_brand = request.form.get("v_brand", "").strip()
            v_model = request.form.get("v_model", "").strip()
            v_colour = request.form.get("v_colour", "").strip()
            v_year_s = request.form.get("v_year", "0").strip()
            if v_reg and v_brand and v_model:
                try:
                    v_year = int(v_year_s)
                except ValueError:
                    v_year = 0
                cust.vehicle     = Vehicle(v_reg, v_brand, v_model, v_colour, v_year)
                cust.has_vehicle = True
            self.customers.append(cust)
            return render_template_string(CUSTOMER_ANON_TMPL,
                page_title="Customer Portal",
                flash_msg="",
                success_msg=f"Account created successfully! Welcome, {name}. Please login.")

        @app.route("/customer/login", methods=["POST"])
        def customer_login():
            phone = request.form.get("phone", "").strip()
            pw    = request.form.get("password", "").strip()
            for i, c in enumerate(self.customers):
                if c.get_phone() == phone and c.check_password(pw):
                    session["customer_idx"] = i
                    return redirect(url_for("customer_dashboard"))
            return render_template_string(CUSTOMER_ANON_TMPL,
                page_title="Customer Portal", flash_msg="Invalid phone or password.", success_msg="")

        @app.route("/customer/logout")
        def customer_logout():
            session.pop("customer_idx", None)
            return redirect(url_for("customer_page"))

        @app.route("/customer/dashboard")
        def customer_dashboard():
            if "customer_idx" not in session:
                return redirect(url_for("customer_page"))
            idx  = session["customer_idx"]
            cust = self.customers[idx]
            my_reqs = []
            for r in self.requests:
                if r.customer_index == idx:
                    pname = r.chosen_part.name if r.chosen_part else "N/A"
                    my_reqs.append({
                        "id":            r.id,
                        "issue":         r.issue,
                        "chosen_part_name": pname,
                        "total_amount":  r.total_amount,
                        "paid":          r.paid,
                        "payment_method": r.payment_method,
                        "roadside":      r.roadside,
                    })
            flash  = session.pop("flash_msg",   "")
            succ   = session.pop("success_msg", "")
            return render_template_string(DASH_TMPL,
                page_title="Dashboard",
                cust_name=cust.get_name(),
                cust_phone=cust.get_phone(),
                has_vehicle=cust.has_vehicle,
                v_reg=cust.vehicle.reg_no if cust.has_vehicle else "",
                v_brand=cust.vehicle.brand if cust.has_vehicle else "",
                v_model=cust.vehicle.model if cust.has_vehicle else "",
                v_colour=cust.vehicle.colour if cust.has_vehicle else "",
                v_year=cust.vehicle.year if cust.has_vehicle else "",
                requests=my_reqs,
                flash_msg=flash,
                success_msg=succ)

        @app.route("/customer/add-vehicle", methods=["GET", "POST"])
        def add_vehicle():
            if "customer_idx" not in session:
                return redirect(url_for("customer_page"))
            if request.method == "POST":
                idx  = session["customer_idx"]
                cust = self.customers[idx]
                try:
                    year = int(request.form.get("v_year", "0"))
                except ValueError:
                    year = 0
                cust.vehicle = Vehicle(
                    reg_no = request.form.get("v_reg", "").strip(),
                    brand  = request.form.get("v_brand", "").strip(),
                    model  = request.form.get("v_model", "").strip(),
                    colour = request.form.get("v_colour", "").strip(),
                    year   = year,
                )
                cust.has_vehicle = True
                session["success_msg"] = "Vehicle added successfully!"
                return redirect(url_for("customer_dashboard"))
            return render_template_string(ADD_VEH_TMPL, page_title="Add Vehicle")

        # ── Service Request (Web) ──
        @app.route("/service/request", methods=["GET", "POST"])
        def service_request():
            if "customer_idx" not in session:
                return redirect(url_for("customer_page"))
            idx  = session["customer_idx"]
            cust = self.customers[idx]

            if request.method == "GET":
                if not cust.has_vehicle:
                    session["flash_msg"] = "Please add a vehicle before requesting service."
                    return redirect(url_for("customer_dashboard"))
                pairs    = self._data_mgr.get_parts_for_vehicle(cust.vehicle.model, cust.vehicle.brand)
                parts_list = [p for p, _ in pairs] if pairs else self.parts
                mechs_info = []
                for i, m in enumerate(self.mechanics):
                    m.available = self._is_mechanic_available(i)
                    mechs_info.append(m)
                veh_str  = f"{cust.vehicle.brand} {cust.vehicle.model} ({cust.vehicle.reg_no})"
                return render_template_string(SERVICE_TMPL,
                    page_title="Request Service",
                    veh_str=veh_str,
                    parts=parts_list,
                    mechanics=mechs_info,
                    locations=self._locations,
                    flash_msg="")

            # POST
            issue      = request.form.get("issue", "").strip()
            part_code  = request.form.get("part_code", "").strip()
            mech_idx_s = request.form.get("mech_idx", "")
            roadside   = request.form.get("roadside", "0") == "1"
            loc_idx_s  = request.form.get("loc_idx", "0")
            payment    = request.form.get("payment", "bKash")

            # Validate
            if not issue or not part_code or not mech_idx_s:
                pairs      = self._data_mgr.get_parts_for_vehicle(cust.vehicle.model, cust.vehicle.brand)
                parts_list = [p for p, _ in pairs] if pairs else self.parts
                mechs_info = []
                for i, m in enumerate(self.mechanics):
                    m.available = self._is_mechanic_available(i)
                    mechs_info.append(m)
                return render_template_string(SERVICE_TMPL,
                    page_title="Request Service",
                    veh_str=f"{cust.vehicle.brand} {cust.vehicle.model}",
                    parts=parts_list,
                    mechanics=mechs_info,
                    locations=self._locations,
                    flash_msg="Please fill in all required fields.")

            try:
                mech_idx = int(mech_idx_s)
            except ValueError:
                mech_idx = 0

            chosen_part = next((p for p in self.parts if p.code == part_code), Part())
            mech        = self.mechanics[mech_idx] if 0 <= mech_idx < len(self.mechanics) else Mechanic()

            req                  = ServiceRequest()
            req.id               = self._next_req_id
            self._next_req_id   += 1
            req.customer_index   = idx
            req.issue            = issue
            req.chosen_part      = chosen_part
            req.mechanic_index   = mech_idx
            req.roadside         = roadside
            req.payment_method   = payment
            req.paid             = True

            if roadside:
                req.delivery_charge = 100.0
                try:
                    li = int(loc_idx_s)
                    if 0 <= li < len(self._locations):
                        lo = self._locations[li]
                        req.location = Location(lo.lat, lo.lon)
                except (ValueError, IndexError):
                    pass
            else:
                req.delivery_charge = 0.0

            req.total_amount = chosen_part.price + mech.rate_per_job + req.delivery_charge
            self.requests.append(req)
            if 0 <= mech_idx < len(self.mechanics):
                self.mechanics[mech_idx].available = False

            # Nationwide search if far from workshop
            nearby_mechs: List[Dict] = []
            if roadside and req.location.is_set():
                ws   = Location(WORKSHOP_LAT, WORKSHOP_LON)
                dist = req.location.distance_to(ws)
                if dist > 100.0:
                    result = self.network.auto_search_and_invite(
                        req.location.lat, req.location.lon, issue, cust.get_name()
                    )
                    if result.get("found"):
                        nearby_mechs = result.get("invited_mechanics", [])

            return render_template_string(CONFIRM_TMPL,
                page_title="Request Confirmed",
                req_id=req.id,
                issue=req.issue,
                part_name=chosen_part.name,
                mech_name=mech.name,
                roadside="Yes" if roadside else "No",
                total=f"{req.total_amount:.2f}",
                payment=payment,
                nearby_mechs=nearby_mechs)

        # ── Admin ──
        @app.route("/admin", methods=["GET"])
        def admin_page():
            if session.get("admin_logged_in"):
                return redirect(url_for("admin_dashboard"))
            return render_template_string(ADMIN_LOGIN_TMPL, page_title="Admin", error="")

        @app.route("/admin/login", methods=["POST"])
        def admin_login():
            u  = request.form.get("username", "")
            pw = request.form.get("password", "")
            if u == self.ADMIN_USER and simple_hash(pw) == self.ADMIN_HASH:
                session["admin_logged_in"] = True
                return redirect(url_for("admin_dashboard"))
            return render_template_string(ADMIN_LOGIN_TMPL, page_title="Admin",
                error="Invalid credentials.")

        @app.route("/admin/logout")
        def admin_logout():
            session.pop("admin_logged_in", None)
            return redirect(url_for("admin_page"))

        @app.route("/admin/dashboard")
        def admin_dashboard():
            if not session.get("admin_logged_in"):
                return redirect(url_for("admin_page"))
            reqs_data = []
            for r in self.requests:
                cname = self.customers[r.customer_index].get_name() if 0 <= r.customer_index < len(self.customers) else "Unknown"
                cphone = self.customers[r.customer_index].get_phone() if 0 <= r.customer_index < len(self.customers) else ""
                mname = self.mechanics[r.mechanic_index].name if 0 <= r.mechanic_index < len(self.mechanics) else "Unknown"
                reqs_data.append({
                    "id":        r.id,
                    "cust_name": cname,
                    "cust_phone": cphone,
                    "issue":     r.issue,
                    "part_name": r.chosen_part.name if r.chosen_part else "N/A",
                    "mech_name": mname,
                    "total":     r.total_amount,
                    "paid":      r.paid,
                    "payment":   r.payment_method or "Pending",
                })
            paid_reqs = [r for r in self.requests if r.paid]
            revenue   = sum(r.total_amount for r in paid_reqs)
            return render_template_string(ADMIN_DASH_TMPL,
                page_title="Admin Dashboard",
                total_customers=len(self.customers),
                total_requests=len(self.requests),
                paid_requests=len(paid_reqs),
                total_revenue=f"{revenue:,.0f}",
                requests=reqs_data,
                invitations=self.network.invitations)

        @app.route("/admin/mark-paid", methods=["POST"])
        def admin_mark_paid():
            if not session.get("admin_logged_in"):
                return redirect(url_for("admin_page"))
            try:
                rid = int(request.form.get("req_id", 0))
            except ValueError:
                rid = 0
            for r in self.requests:
                if r.id == rid:
                    r.paid = True
                    if not r.payment_method:
                        r.payment_method = "Admin (Cash)"
                    if 0 <= r.mechanic_index < len(self.mechanics):
                        self.mechanics[r.mechanic_index].available = True
                    break
            return redirect(url_for("admin_dashboard"))

        # ── Export Bills ──
        @app.route("/export/bills")
        def export_bills():
            if not session.get("admin_logged_in"):
                return redirect(url_for("admin_page"))
            self._generate_bills_csv("bills.csv")
            return "<p style='font-family:sans-serif;padding:20px'>✅ bills.csv exported! <a href='/admin/dashboard'>← Back</a></p>"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_mechanic_available(self, idx: int) -> bool:
        for r in self.requests:
            if r.mechanic_index == idx and not r.paid:
                return False
        return True

    def _generate_bills_csv(self, filename: str = "bills.csv"):
        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Request ID", "Customer Name", "Phone", "Vehicle Reg",
                    "Issue", "Part Name", "Part Code", "Part Price",
                    "Mechanic Name", "Mechanic Code", "Mechanic Rate",
                    "Delivery", "Roadside", "GPS Location", "Total", "Paid", "Payment"
                ])
                for r in self.requests:
                    ci   = r.customer_index
                    mi   = r.mechanic_index
                    cust = self.customers[ci] if 0 <= ci < len(self.customers) else None
                    mech = self.mechanics[mi] if 0 <= mi < len(self.mechanics) else None
                    writer.writerow([
                        r.id,
                        cust.get_name() if cust else "Unknown",
                        cust.get_phone() if cust else "",
                        cust.vehicle.reg_no if cust and cust.has_vehicle else "",
                        r.issue,
                        r.chosen_part.name if r.chosen_part else "",
                        r.chosen_part.code if r.chosen_part else "",
                        r.chosen_part.price if r.chosen_part else 0,
                        mech.name if mech else "Unknown",
                        mech.code if mech else "",
                        mech.rate_per_job if mech else 0,
                        r.delivery_charge,
                        "Yes" if r.roadside else "No",
                        str(r.location) if r.roadside and r.location.is_set() else "",
                        r.total_amount,
                        "Yes" if r.paid else "No",
                        r.payment_method or "Unpaid",
                    ])
            print(f"  [Export] Bills written to {filename}")
            open_file_cross_platform(filename)
        except IOError as e:
            print(f"  [Export] Failed: {e}")

    # ═════════════════════════════════════════════════════════════════════════
    #  CONSOLE MODE
    # ═════════════════════════════════════════════════════════════════════════

    def show_welcome(self):
        print("\n" + "=" * 70)
        print("   🚗  RoadRescue — Workshop Management & Breakdown Assistance System")
        print(f"        {VERSION}  |  Group 8 (Tanvir-2485, Hafiz-2450, Shahajalal-2451)")
        print(f"        Department of CSE, Northern University Bangladesh")
        print("=" * 70)
        print(f"  AI Status : {self.ai.status_label}")
        print(f"  Mechanics : {len(self.mechanics)} (workshop) + {len(self.network.mechanics)} (nationwide)")
        print(f"  Parts     : {len(self.parts)} loaded")
        print(f"  Locations : {len(self._locations)} loaded from locations.txt")
        print()

    def run_console(self):
        self.show_welcome()
        while True:
            print("\n─── MAIN MENU ─────────────────────────────────────")
            print("  1) Customer Portal")
            print("  2) Admin Panel")
            print("  3) Guest Demo (parts & mechanics)")
            print("  4) Export Bills (CSV)")
            print("  5) Start Web Interface  ← recommended for demo")
            print("  6) Exit")
            ch = read_int("  Choose: ")
            if   ch == 1: self._console_customer_portal()
            elif ch == 2: self._console_admin_panel()
            elif ch == 3: self._console_guest_demo()
            elif ch == 4: self._generate_bills_csv()
            elif ch == 5: self._start_web()
            elif ch == 6: print("  Goodbye! 🚗"); break

    def _start_web(self):
        print("\n  ✅ Starting web interface at http://127.0.0.1:5000")
        print("  Press CTRL+C to stop.\n")
        self.app.run(debug=False, port=5000, use_reloader=False)

    def _console_customer_portal(self):
        while True:
            print("\n  Customer Menu:")
            print("  1) Register   2) Login   3) Back")
            ch = read_int("  Choose: ")
            if ch == 1:
                self._console_register()
            elif ch == 2:
                idx = self._console_login()
                if idx >= 0:
                    self._console_dashboard(idx)
            elif ch == 3:
                break

    def _console_register(self):
        name  = read_line("  Full Name: ")
        phone = read_line("  Phone: ")
        for c in self.customers:
            if c.phone == phone:
                print("  ❌ Phone already registered!")
                return
        pw   = read_line("  Password: ")
        cust = Customer(name, phone, pw)
        cust.id = len(self.customers) + 1
        self.customers.append(cust)
        print(f"  ✅ Registered successfully! Welcome, {name}.")

    def _console_login(self) -> int:
        phone = read_line("  Phone: ")
        pw    = read_line("  Password: ")
        for i, c in enumerate(self.customers):
            if c.get_phone() == phone and c.check_password(pw):
                return i
        print("  ❌ Invalid credentials.")
        return -1

    def _console_dashboard(self, idx: int):
        cust = self.customers[idx]
        while True:
            print(f"\n  Dashboard — {cust.get_name()}")
            print("  1) Add Vehicle   2) View Vehicle   3) Request Service")
            print("  4) My Requests   5) AI Diagnosis   6) Logout")
            ch = read_int("  Choose: ")
            if   ch == 1: cust.add_vehicle()
            elif ch == 2: cust.show_vehicle()
            elif ch == 3: self._console_create_request(idx)
            elif ch == 4: self._console_view_requests(idx)
            elif ch == 5: self._console_ai_diagnose()
            elif ch == 6: break

    def _console_ai_diagnose(self):
        problem = read_line("  Describe your problem: ")
        vehicle = read_line("  Vehicle (optional): ")
        print("\n  🤖 Analyzing with AI...")
        result = self.ai.diagnose_problem(problem, vehicle)
        print(f"\n  Source: {result.get('source_label', 'AI')}")
        print("  " + "─" * 50)
        print(result.get("response", "No response."))
        print("  " + "─" * 50)

        img_ch = read_int("  Upload image for damage detection? (1=Yes / 0=No): ")
        if img_ch == 1:
            path = read_line("  Image file path: ")
            try:
                with open(path, "rb") as f:
                    img_bytes = f.read()
                mime = "image/jpeg"
                if path.lower().endswith(".png"): mime = "image/png"
                result2 = self.ai.analyze_vehicle_image(img_bytes, mime)
                print(f"\n  Source: {result2.get('source_label', 'Vision AI')}")
                print("  " + "─" * 50)
                print(result2.get("analysis", "No analysis."))
            except FileNotFoundError:
                print("  ❌ File not found.")

    def _console_create_request(self, cust_idx: int):
        cust = self.customers[cust_idx]
        if not cust.has_vehicle:
            print("  Please add a vehicle first.")
            return

        req                = ServiceRequest()
        req.id             = self._next_req_id
        self._next_req_id += 1
        req.customer_index = cust_idx
        req.issue          = read_line("  Describe the issue: ")

        # AI suggestions
        print("\n  🤖 Getting AI suggestions...")
        res = self.ai.diagnose_problem(req.issue, f"{cust.vehicle.brand} {cust.vehicle.model}")
        print(f"  {res.get('source_label','AI')}:")
        print("  " + res.get("response", "").replace("\n", "\n  "))

        # Parts
        pairs = self._data_mgr.get_parts_for_vehicle(cust.vehicle.model, cust.vehicle.brand)
        if not pairs:
            pairs = [(p, "fallback") for p in self.parts]
        print(f"\n  Parts for {cust.vehicle.brand} {cust.vehicle.model}:")
        print(f"  {'#':<4}{'Name':<30}{'Code':<12}{'Price':>10}  Match")
        print("  " + "─" * 62)
        for i, (p, mt) in enumerate(pairs, 1):
            print(f"  {i:<4}{p.name:<30}{p.code:<12}Tk {p.price:>8.2f}  [{mt}]")
        pc = read_int("  Choose part: ")
        if not (1 <= pc <= len(pairs)):
            print("  Invalid choice."); return
        req.chosen_part = pairs[pc - 1][0]

        # Mechanic
        print("\n  Available Mechanics:")
        for i, m in enumerate(self.mechanics):
            m.available = self._is_mechanic_available(i)
            print(f"  {i+1}) ", end=""); m.display()
        mc = read_int("  Choose mechanic: ")
        if not (1 <= mc <= len(self.mechanics)) or not self.mechanics[mc - 1].available:
            print("  Invalid or busy."); return
        req.mechanic_index = mc - 1
        mech = self.mechanics[req.mechanic_index]

        # Roadside
        road = read_int("  Need roadside help? (1=Yes / 0=No): ")
        req.roadside = (road == 1)
        if req.roadside:
            if self._locations:
                req.location = Location.input_from_list(self._locations)
            else:
                raw = input("  Enter lat,lon: ").strip()
                if "," in raw:
                    try:
                        la, lo = raw.split(",", 1)
                        req.location = Location(float(la), float(lo))
                    except ValueError:
                        pass

            if req.location.is_set():
                ws   = Location(WORKSHOP_LAT, WORKSHOP_LON)
                dist = req.location.distance_to(ws)
                print(f"  Your location: {req.location}")
                print(f"  Distance from workshop: {dist:.2f} km")
                if dist > 100:
                    print("\n  📍 You are far from the workshop. Searching nationwide...")
                    result = self.network.auto_search_and_invite(
                        req.location.lat, req.location.lon, req.issue, cust.get_name()
                    )
                    if result.get("found"):
                        print(f"  ✅ {result['message']}")
                        for m in result.get("invited_mechanics", []):
                            print(f"     → {m['name']} ({m['expertise']}) — {m['distance_km']} km | 📞 {m['contact']}")
                    else:
                        print(f"  ⚠️  {result['message']}")

        req.delivery_charge = 100.0 if req.roadside else 0.0
        req.total_amount    = req.chosen_part.price + mech.rate_per_job + req.delivery_charge

        # Payment
        self._console_take_payment(req)
        self.requests.append(req)
        mech.available = False

        print(f"\n  ✅ Service Request #{req.id} created!")
        print(f"  Part    : {req.chosen_part.name}  Tk {req.chosen_part.price:.2f}")
        print(f"  Mechanic: {mech.name}  Tk {mech.rate_per_job:.2f}")
        if req.delivery_charge:
            print(f"  Delivery: Tk {req.delivery_charge:.2f}")
        print(f"  TOTAL   : Tk {req.total_amount:.2f}")
        print(f"  Payment : {'✅ ' + req.payment_method if req.paid else '⏳ Pending'}")

    def _console_take_payment(self, req: ServiceRequest) -> bool:
        print(f"\n  ═══ PAYMENT  ═══  Total: Tk {req.total_amount:.2f}")
        print("  1) bKash  2) Nagad  3) Card  4) Pay Later")
        opt = read_int("  Choose: ")
        if opt == 1:
            read_line("  bKash Number: ")
            read_line("  Transaction ID: ")
            req.payment_method = "bKash"; req.paid = True
            print("  ✅ bKash payment confirmed!")
        elif opt == 2:
            read_line("  Nagad Number: ")
            read_line("  Transaction ID: ")
            req.payment_method = "Nagad"; req.paid = True
            print("  ✅ Nagad payment confirmed!")
        elif opt == 3:
            read_line("  Card Number (16 digits): ")
            read_line("  Name on Card: ")
            read_line("  OTP: ")
            req.payment_method = "Card"; req.paid = True
            print("  ✅ Card payment confirmed!")
        else:
            req.payment_method = "Pending"; req.paid = False
            print("  ⏳ Payment deferred. Admin can collect later.")
        return req.paid

    def _console_view_requests(self, cust_idx: int):
        print("\n  ─── My Requests ───")
        found = False
        for r in self.requests:
            if r.customer_index == cust_idx:
                found = True
                status = f"✅ {r.payment_method}" if r.paid else "⏳ Pending"
                print(f"  #{r.id} | {r.issue} | Tk {r.total_amount:.2f} | {status}")
                if r.roadside:
                    print(f"       Location: {r.get_location_string()}")
        if not found:
            print("  No requests yet.")

    def _console_admin_panel(self):
        user = read_line("  Admin Username: ")
        pw   = read_line("  Admin Password: ")
        if user != self.ADMIN_USER or simple_hash(pw) != self.ADMIN_HASH:
            print("  ❌ Invalid admin credentials.")
            return
        print("\n  ─── ADMIN PANEL ───")
        if not self.requests:
            print("  No requests yet.")
        for r in self.requests:
            ci = r.customer_index
            mi = r.mechanic_index
            cn = self.customers[ci].get_name() if 0 <= ci < len(self.customers) else "?"
            mn = self.mechanics[mi].name if 0 <= mi < len(self.mechanics) else "?"
            st = f"✅ {r.payment_method}" if r.paid else "⏳ PENDING"
            print(f"  #{r.id} | {cn} | {mn} | Tk {r.total_amount:.2f} | {st}")
            if r.roadside:
                print(f"        Location: {r.get_location_string()}")

        if self.network.invitations:
            print(f"\n  ─── Mechanic Invitations ({len(self.network.invitations)}) ───")
            for inv in self.network.invitations:
                print(f"  📨 {inv['name']} ({inv['city']}, {inv.get('distance_km','?')} km) ← {inv['customer_name']} | {inv['timestamp']}")

        try:
            rid = int(input("\n  Mark request as paid (ID, 0 to skip): ").strip())
        except ValueError:
            rid = 0
        if rid:
            for req in self.requests:
                if req.id == rid and not req.paid:
                    self._console_take_payment(req)
                    if 0 <= req.mechanic_index < len(self.mechanics):
                        self.mechanics[req.mechanic_index].available = True
                    return
            print("  Request not found or already paid.")

    def _console_guest_demo(self):
        print("\n  ─── GUEST DEMO ───")
        print("\n  Sample Parts:")
        for p in self.parts[:8]:
            p.display()
        print("\n  Workshop Mechanics:")
        for i, m in enumerate(self.mechanics):
            m.available = self._is_mechanic_available(i)
            m.display()
        print(f"\n  Nationwide mechanics loaded: {len(self.network.mechanics)}")
        if self._locations:
            print(f"  Location areas available : {len(self._locations)}")
        ai_demo = read_int("  Run AI demo? (1=Yes / 0=No): ")
        if ai_demo == 1:
            self._console_ai_diagnose()

    # ── Web entry point ───────────────────────────────────────────────────────

    def run_web(self, port: int = 5000, debug: bool = False):
        print(f"\n  🌐  Starting RoadRescue Web Interface at http://127.0.0.1:{port}")
        print(f"  🤖  AI Status: {self.ai.status_label}")
        print(f"  📡  Open browser and navigate to http://127.0.0.1:{port}")
        print("      Press CTRL+C to stop.\n")
        self.app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)


# ═════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mgr = SystemManager()

    if "--console" in sys.argv:
        mgr.run_console()
    elif "--web" in sys.argv:
        port  = 5000
        debug = "--debug" in sys.argv
        mgr.run_web(port=port, debug=debug)
    else:
        # Interactive startup menu
        mgr.show_welcome()
        print("\n  ┌──────────────────────────────────────────┐")
        print("  │  How would you like to run RoadRescue?   │")
        print("  ├──────────────────────────────────────────┤")
        print("  │  1) 🌐 Web Interface   ← RECOMMENDED     │")
        print("  │        http://127.0.0.1:5000              │")
        print("  │  2) 💻 Console Mode                       │")
        print("  └──────────────────────────────────────────┘")
        ch = read_int("  Choose (1 or 2): ")
        if ch == 1:
            mgr.run_web(port=5000, debug=False)
        else:
            mgr.run_console()

if __name__ == "__main__":
    system = SystemManager()

    if "--web" in sys.argv:
        # Web mode — you need Flask routes defined first
        # (see app.py from the earlier backend file)
        print("Web mode not yet integrated. Run without --web for console mode.")
    else:
        # Console mode — works right now
        system.run()