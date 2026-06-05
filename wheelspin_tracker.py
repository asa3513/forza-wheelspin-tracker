"""
Forza Horizon Wheelspin Tracker
- 일반 휠스핀: CR 영역 + 차량 영역 2개 직접 지정
- 슈퍼 휠스핀: 3열 × 2개 = 6개 영역 직접 지정
- 토글로 모드 전환
"""

import mss
import cv2
import numpy as np
import pytesseract
from PIL import Image
import pandas as pd
import time
import os
import json
import re
from datetime import datetime
import keyboard
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import csv
import ctypes
import logging
import traceback

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

SAVE_FILE = "wheelspin_records.csv"
WISHLIST_FILE = "exclusive_cars.txt"

# 에러 로그 설정
LOG_FILE = "wheelspin_error.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8"
)

def log_error(msg: str, exc: Exception = None):
    if exc:
        logging.error(f"{msg}\n{traceback.format_exc()}")
    else:
        logging.error(msg)
CONFIG_FILE = "wheelspin_config.json"

DEFAULT_CONFIG = {
    "hotkey": "f9",
    "normal_regions": {
        "cr":  {"top": 400, "left": 1800, "width": 600, "height": 150},
        "car": {"top": 400, "left": 1800, "width": 600, "height": 150},
    },
    "super_regions": {
        "col1_cr":  {"top": 400, "left": 1300, "width": 350, "height": 120},
        "col1_car": {"top": 400, "left": 1300, "width": 350, "height": 120},
        "col2_cr":  {"top": 400, "left": 1700, "width": 350, "height": 120},
        "col2_car": {"top": 400, "left": 1700, "width": 350, "height": 120},
        "col3_cr":  {"top": 400, "left": 2100, "width": 350, "height": 120},
        "col3_car": {"top": 400, "left": 2100, "width": 350, "height": 120},
    }
}

# ── OCR ──────────────────────────────────────────

def select_region_by_drag(title: str = "영역 선택") -> dict | None:
    """
    반투명 전체화면 오버레이에서 마우스 드래그로 영역 선택.
    ESC: 취소, 마우스 드래그: 영역 지정
    """
    result = {}
    dragging = False
    start_x = start_y = end_x = end_y = 0

    # 전체 화면 크기
    root_tmp = tk.Tk()
    root_tmp.withdraw()
    sw = root_tmp.winfo_screenwidth()
    sh = root_tmp.winfo_screenheight()
    root_tmp.destroy()

    overlay = tk.Toplevel()
    overlay.attributes('-fullscreen', True)
    overlay.attributes('-alpha', 0.35)
    overlay.attributes('-topmost', True)
    overlay.configure(bg='black')
    overlay.title(title)

    canvas = tk.Canvas(overlay, cursor='crosshair',
                       bg='black', highlightthickness=0)
    canvas.pack(fill='both', expand=True)

    # 안내 텍스트
    canvas.create_text(sw // 2, 40, text=f"[ {title} ]  드래그로 영역 선택  |  ESC: 취소",
                       fill='white', font=('Consolas', 16, 'bold'))

    rect_id = None

    def on_press(e):
        nonlocal dragging, start_x, start_y, rect_id
        dragging = True
        start_x, start_y = e.x, e.y
        if rect_id:
            canvas.delete(rect_id)

    def on_drag(e):
        nonlocal rect_id, end_x, end_y
        end_x, end_y = e.x, e.y
        if rect_id:
            canvas.delete(rect_id)
        rect_id = canvas.create_rectangle(
            start_x, start_y, end_x, end_y,
            outline='#00d4ff', width=2, fill='#00d4ff', stipple='gray25'
        )
        # 크기 표시
        canvas.delete('size_label')
        w = abs(end_x - start_x)
        h = abs(end_y - start_y)
        canvas.create_text(end_x + 5, end_y + 5,
                           text=f'{w}×{h}', fill='#00d4ff',
                           font=('Consolas', 11), anchor='nw', tags='size_label')

    def on_release(e):
        nonlocal dragging, result
        dragging = False
        x1, y1 = min(start_x, e.x), min(start_y, e.y)
        x2, y2 = max(start_x, e.x), max(start_y, e.y)
        if x2 - x1 > 5 and y2 - y1 > 5:
            result = {"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1}
        overlay.destroy()

    def on_escape(e):
        overlay.destroy()

    canvas.bind('<ButtonPress-1>', on_press)
    canvas.bind('<B1-Motion>', on_drag)
    canvas.bind('<ButtonRelease-1>', on_release)
    overlay.bind('<Escape>', on_escape)
    overlay.focus_force()
    overlay.wait_window()

    return result if result else None


def load_wishlist() -> list:
    if os.path.exists(WISHLIST_FILE):
        try:
            with open(WISHLIST_FILE, 'r', encoding='utf-8') as f:
                return [l.strip() for l in f.readlines() if l.strip() and not l.startswith('#')]
        except:
            pass
    return []

def save_wishlist(lst: list):
    with open(WISHLIST_FILE, 'w', encoding='utf-8') as f:
        f.write('# exclusive cars - one per line\n\n')
        for item in lst:
            f.write(item + '\n')

def check_wishlist(text: str, wishlist: list) -> bool:
    """아이템명이 위시리스트 항목과 매칭되는지 확인 (부분 일치)"""
    t = text.lower()
    return any(w.lower() in t for w in wishlist if w.strip())


def capture_region(region: dict) -> np.ndarray:
    with mss.MSS() as sct:
        shot = sct.grab(region)
        img = np.array(shot)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

def ocr_image(img: np.ndarray) -> str:
    """검정 텍스트만 추출해서 OCR"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    black_mask = cv2.inRange(hsv, (0, 0, 0), (180, 255, 80))
    result = np.full(img.shape[:2], 255, dtype=np.uint8)
    result[black_mask > 0] = 0

    h, w = result.shape
    result = cv2.resize(result, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)

    kernel = np.array([[0,-1,0],[-1,5,-1],[0,-1,0]], dtype=np.float32)
    result = cv2.filter2D(result, -1, kernel)
    _, result = cv2.threshold(result, 128, 255, cv2.THRESH_BINARY)

    pil = Image.fromarray(result)
    try:
        raw = pytesseract.image_to_string(pil, config='--oem 3 --psm 3 -l eng+kor')
        return clean_text(raw)
    except Exception as e:
        log_error("OCR 실패", e)
        return ""

def has_cr_logo(img: np.ndarray) -> bool:
    """노란 CR 로고 원형이 이미지에 있는지 감지"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # 노란색 마스크
    yellow = cv2.inRange(hsv, (18, 120, 150), (35, 255, 255))
    # 원형 감지
    yellow_blur = cv2.GaussianBlur(yellow, (9, 9), 2)
    circles = cv2.HoughCircles(yellow_blur, cv2.HOUGH_GRADIENT,
                                dp=1, minDist=20,
                                param1=50, param2=15,
                                minRadius=8, maxRadius=60)
    return circles is not None


def clean_text(text: str) -> str:
    lines = text.splitlines()
    out = []
    for line in lines:
        line = re.sub(r'[^a-zA-Z0-9가-힣\s,.\-\'#]+', '', line).strip()
        if len(line) >= 1:
            out.append(line)
    return ' '.join(out).strip()

def extract_credits(text: str) -> int:
    nums = re.findall(r'\b\d[\d,]+\b', text)
    for n in nums:
        val = int(re.sub(r'[^\d]', '', n))
        if val >= 100:
            return val
    return 0

def classify(text: str) -> str:
    t = text.lower()
    car_kw = ["subaru","toyota","honda","nissan","mazda","ford","chevrolet","ferrari",
              "lamborghini","porsche","bmw","mercedes","audi","corvette","mustang",
              "brz","wrx","gtr","supra","civic","rx7","miata","camaro","charger",
              "reliant","alumicraft","acura","shelby","dodge","jeep","buick","cadillac",
              "trick truck","supervan","edition"]
    if any(k in t for k in car_kw):
        return "차량"
    if re.search(r'\b(19[5-9]\d|20[012]\d)\b', t):
        return "차량"
    if re.search(r'\b\d[\d,]{2,}\b', t):
        return "크레딧"
    return "기타"

def save_record(record: dict):
    exists = os.path.exists(SAVE_FILE)
    with open(SAVE_FILE, 'a', newline='', encoding='utf-8-sig') as f:
        fields = ["timestamp", "spin_type", "item_type", "item_name", "credits"]
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        if not exists:
            w.writeheader()
        w.writerow(record)

def load_records() -> list:
    if not os.path.exists(SAVE_FILE):
        return []
    try:
        df = pd.read_csv(SAVE_FILE, encoding='utf-8-sig')
        return df.fillna('').to_dict('records')
    except:
        return []

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                # 키 누락 방지
                for k, v in DEFAULT_CONFIG.items():
                    if k not in cfg:
                        cfg[k] = v
                return cfg
        except:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg: dict):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# ── GUI ──────────────────────────────────────────

class WheelspinTracker:
    def __init__(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            dpi = ctypes.windll.user32.GetDpiForSystem()
            self.scale = dpi / 96.0
        except:
            self.scale = 1.0

        self.config = load_config()
        self.records = load_records()
        self.wishlist = load_wishlist()

        self.root = tk.Tk()
        self.spin_mode = tk.StringVar(value="일반")  # 일반 / 슈퍼
        self.root.title("🎡 Forza Wheelspin Tracker")
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        s = self.scale
        ww = min(int(980 * s), sw - 80)
        wh = min(int(660 * s), sh - 80)
        self.root.geometry(f"{ww}x{wh}")
        self.root.configure(bg="#0a0a0f")
        self.root.resizable(True, True)

        self._build_ui()
        self._refresh_table()
        self._update_stats()
        self._register_hotkey()

    def fs(self, n):
        return max(7, int(n * self.scale))

    def px(self, n):
        return max(1, int(n * self.scale))

    def _build_ui(self):
        BG = "#0a0a0f"
        PANEL = "#12121a"
        ACCENT = "#00d4ff"
        TEXT = "#e8e8f0"
        MUTED = "#5a5a7a"
        SUCCESS = "#00ff88"
        fs, px = self.fs, self.px

        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Treeview", background=PANEL, foreground=TEXT,
                        fieldbackground=PANEL, rowheight=px(28), font=("Consolas", fs(9)))
        style.configure("Treeview.Heading", background="#1e1e2e", foreground=ACCENT,
                        font=("Consolas", fs(9), "bold"))
        style.map("Treeview", background=[("selected", "#1a3a5c")])

        # 헤더
        header = tk.Frame(self.root, bg="#0d0d18", height=px(55))
        header.pack(fill='x')
        header.pack_propagate(False)
        tk.Label(header, text="⬡ FORZA WHEELSPIN TRACKER",
                 font=("Consolas", fs(15), "bold"), fg=ACCENT, bg="#0d0d18").pack(side='left', padx=px(16), pady=px(12))
        self.status_label = tk.Label(header, text="● 대기중",
                                     font=("Consolas", fs(9)), fg=MUTED, bg="#0d0d18")
        self.status_label.pack(side='right', padx=px(16))

        # 메인
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill='both', expand=True, padx=px(10), pady=px(8))

        # ── 왼쪽 패널 ──
        left = tk.Frame(main, bg=PANEL, width=px(230))
        left.pack(side='left', fill='y', padx=(0, px(8)))
        left.pack_propagate(False)

        # 모드 토글
        mode_frame = tk.Frame(left, bg=PANEL)
        mode_frame.pack(fill='x', padx=px(10), pady=(px(12), px(4)))
        tk.Label(mode_frame, text="모드", font=("Consolas", fs(9), "bold"),
                 fg=ACCENT, bg=PANEL).pack(anchor='w')

        toggle_frame = tk.Frame(mode_frame, bg="#1e1e2e", bd=0)
        toggle_frame.pack(fill='x', pady=px(4))

        self.btn_normal = tk.Button(toggle_frame, text="🎡 일반",
                                    font=("Consolas", fs(9), "bold"),
                                    fg="#0a0a0f", bg=ACCENT,
                                    relief='flat', bd=0, cursor='hand2',
                                    command=lambda: self._set_mode("일반"))
        self.btn_normal.pack(side='left', expand=True, fill='x', padx=(2,1), pady=2)

        self.btn_super = tk.Button(toggle_frame, text="🌟 슈퍼",
                                   font=("Consolas", fs(9), "bold"),
                                   fg=TEXT, bg="#2a2a3e",
                                   relief='flat', bd=0, cursor='hand2',
                                   command=lambda: self._set_mode("슈퍼"))
        self.btn_super.pack(side='left', expand=True, fill='x', padx=(1,2), pady=2)

        ttk.Separator(left, orient='horizontal').pack(fill='x', padx=px(10), pady=px(8))

        # 영역 설정
        self.region_frame = tk.Frame(left, bg=PANEL)
        self.region_frame.pack(fill='x', padx=px(10))
        self._build_region_ui()

        ttk.Separator(left, orient='horizontal').pack(fill='x', padx=px(10), pady=px(8))

        # 단축키
        hk_frame = tk.Frame(left, bg=PANEL)
        hk_frame.pack(fill='x', padx=px(10))
        tk.Label(hk_frame, text="단축키", font=("Consolas", fs(9), "bold"),
                 fg=ACCENT, bg=PANEL).pack(anchor='w')
        self.hotkey_var = tk.StringVar(value=self.config.get("hotkey", "f9"))
        hk_entry = tk.Entry(hk_frame, textvariable=self.hotkey_var,
                            font=("Consolas", fs(10)), bg="#1e1e2e", fg=ACCENT,
                            insertbackground=ACCENT, relief='flat', bd=4,
                            width=8, justify='center')
        hk_entry.pack(pady=px(4))
        tk.Button(hk_frame, text="단축키 저장",
                  font=("Consolas", fs(8)), fg="#0a0a0f", bg=ACCENT,
                  relief='flat', bd=0, cursor='hand2',
                  command=self._save_hotkey).pack(fill='x', pady=(0, px(2)))

        ttk.Separator(left, orient='horizontal').pack(fill='x', padx=px(10), pady=px(8))

        # 버튼들
        tk.Button(left, text="📸  지금 캡처",
                  font=("Consolas", fs(10), "bold"), fg="#0a0a0f", bg=ACCENT,
                  activebackground="#00aacc", relief='flat', bd=0, cursor='hand2', height=2,
                  command=self._manual_capture).pack(fill='x', padx=px(10), pady=px(2))

        tk.Button(left, text="💾  영역 저장",
                  font=("Consolas", fs(9)), fg=TEXT, bg="#1e1e2e",
                  relief='flat', bd=0, cursor='hand2',
                  command=self._save_regions).pack(fill='x', padx=px(10), pady=px(2))

        tk.Button(left, text="🔍  영역 미리보기",
                  font=("Consolas", fs(9)), fg=TEXT, bg="#1e1e2e",
                  relief='flat', bd=0, cursor='hand2',
                  command=self._preview_regions).pack(fill='x', padx=px(10), pady=px(2))

        tk.Button(left, text="⭐  독점 차량 관리",
                  font=("Consolas", fs(9)), fg="#ffcc00", bg="#1e1e2e",
                  relief='flat', bd=0, cursor='hand2',
                  command=self._open_wishlist).pack(fill='x', padx=px(10), pady=px(2))

        tk.Button(left, text="📊  엑셀 내보내기",
                  font=("Consolas", fs(9)), fg=TEXT, bg="#1e1e2e",
                  relief='flat', bd=0, cursor='hand2',
                  command=self._export_excel).pack(fill='x', padx=px(10), pady=px(2))

        tk.Button(left, text="🗑  기록 초기화",
                  font=("Consolas", fs(9)), fg=MUTED, bg=PANEL,
                  relief='flat', bd=0, cursor='hand2',
                  command=self._clear_records).pack(fill='x', padx=px(10), pady=px(2))

        tk.Button(left, text="🪲  에러 로그 보기",
                  font=("Consolas", fs(9)), fg="#ff6666", bg=PANEL,
                  relief='flat', bd=0, cursor='hand2',
                  command=self._open_error_log).pack(fill='x', padx=px(10), pady=px(2))

        # ── 오른쪽 ──
        right = tk.Frame(main, bg=BG)
        right.pack(side='left', fill='both', expand=True)

        # 통계
        stats_bar = tk.Frame(right, bg=PANEL, height=px(75))
        stats_bar.pack(fill='x', pady=(0, px(8)))
        stats_bar.pack_propagate(False)
        self.stat_vars = {}
        for label, key, color in [
            ("총 횟수", "total", ACCENT),
            ("차량", "cars", "#ffcc00"),
            ("크레딧 합계", "credits", SUCCESS),
            ("기타", "etc", "#cc88ff"),
        ]:
            col = tk.Frame(stats_bar, bg=PANEL)
            col.pack(side='left', expand=True, fill='both', padx=2)
            var = tk.StringVar(value="0")
            self.stat_vars[key] = var
            tk.Label(col, textvariable=var, font=("Consolas", fs(18), "bold"),
                     fg=color, bg=PANEL).pack(pady=(px(8), 0))
            tk.Label(col, text=label, font=("Consolas", fs(8)),
                     fg=MUTED, bg=PANEL).pack()

        # 테이블
        table_frame = tk.Frame(right, bg=BG)
        table_frame.pack(fill='both', expand=True)

        cols = ("시간", "모드", "타입", "아이템명")
        self.tree = ttk.Treeview(table_frame, columns=cols, show='headings', selectmode='browse')
        for col in cols:
            self.tree.heading(col, text=col)
        self.tree.column("시간",   width=px(145), anchor='center')
        self.tree.column("모드",   width=px(75),  anchor='center')
        self.tree.column("타입",   width=px(65),  anchor='center')
        self.tree.column("아이템명", width=px(350))

        sb = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        # OCR 미리보기
        ocr_bar = tk.Frame(right, bg=PANEL, height=px(55))
        ocr_bar.pack(fill='x', pady=(px(6), 0))
        ocr_bar.pack_propagate(False)
        tk.Label(ocr_bar, text="마지막 OCR:", font=("Consolas", fs(8)),
                 fg=MUTED, bg=PANEL).pack(anchor='w', padx=px(10), pady=(px(5), 0))
        self.ocr_label = tk.Label(ocr_bar, text="—", font=("Consolas", fs(9)),
                                  fg=TEXT, bg=PANEL, wraplength=px(580), justify='left')
        self.ocr_label.pack(anchor='w', padx=px(10))
        self._setup_tree_tags()

    def _build_region_ui(self):
        """현재 모드에 맞는 영역 설정 UI 생성"""
        for w in self.region_frame.winfo_children():
            w.destroy()

        PANEL = "#12121a"
        MUTED = "#5a5a7a"
        TEXT = "#e8e8f0"
        ACCENT = "#00d4ff"
        fs, px = self.fs, self.px

        mode = self.spin_mode.get()
        cfg_key = "normal_regions" if mode == "일반" else "super_regions"
        regions = self.config.get(cfg_key, DEFAULT_CONFIG[cfg_key])

        tk.Label(self.region_frame, text="캡처 영역",
                 font=("Consolas", fs(9), "bold"), fg=ACCENT, bg=PANEL).pack(anchor='w', pady=(0, px(4)))

        self.region_vars = {}
        labels = {
            "cr": "CR 영역", "car": "차량 영역",
            "col1_cr": "1열 CR", "col1_car": "1열 차량",
            "col2_cr": "2열 CR", "col2_car": "2열 차량",
            "col3_cr": "3열 CR", "col3_car": "3열 차량",
        }

        for key, region in regions.items():
            row_frame = tk.Frame(self.region_frame, bg=PANEL)
            row_frame.pack(fill='x', pady=px(1))
            tk.Label(row_frame, text=labels.get(key, key),
                     font=("Consolas", fs(8)), fg=MUTED, bg=PANEL,
                     width=8, anchor='w').pack(side='left')
            self.region_vars[key] = {}
            for k in ["left", "top", "width", "height"]:
                var = tk.StringVar(value=str(region.get(k, 0)))
                self.region_vars[key][k] = var
                tk.Entry(row_frame, textvariable=var, font=("Consolas", fs(7)),
                         bg="#1e1e2e", fg=TEXT, insertbackground=ACCENT,
                         relief='flat', bd=2, width=5).pack(side='left', padx=1)
            # 드래그 버튼
            tk.Button(row_frame, text="✥",
                      font=("Consolas", fs(8)), fg="#00d4ff", bg="#1e1e2e",
                      relief='flat', bd=0, cursor='hand2',
                      command=lambda k=key: self._drag_select(k)
                      ).pack(side='left', padx=(px(2), 0))

    def _set_mode(self, mode: str):
        self.spin_mode.set(mode)
        ACCENT = "#00d4ff"
        TEXT = "#e8e8f0"
        if mode == "일반":
            self.btn_normal.config(fg="#0a0a0f", bg=ACCENT)
            self.btn_super.config(fg=TEXT, bg="#2a2a3e")
        else:
            self.btn_super.config(fg="#0a0a0f", bg="#ffcc00")
            self.btn_normal.config(fg=TEXT, bg="#2a2a3e")
        self._build_region_ui()

    def _get_regions_from_ui(self) -> dict:
        regions = {}
        for key, kvars in self.region_vars.items():
            try:
                regions[key] = {k: int(v.get()) for k, v in kvars.items()}
            except:
                pass
        return regions

    def _open_error_log(self):
        """에러 로그 뷰어 창"""
        win = tk.Toplevel(self.root)
        win.title("🪲 에러 로그")
        win.geometry(f"{self.px(700)}x{self.px(450)}")
        win.configure(bg="#0a0a0f")

        PANEL = "#12121a"; TEXT = "#e8e8f0"; MUTED = "#5a5a7a"
        fs, px = self.fs, self.px

        # 상단 버튼
        btn_frame = tk.Frame(win, bg="#0a0a0f")
        btn_frame.pack(fill='x', padx=px(10), pady=px(8))
        tk.Label(btn_frame, text="🪲 에러 로그",
                 font=("Consolas", fs(11), "bold"), fg="#ff6666", bg="#0a0a0f").pack(side='left')

        def refresh():
            text_box.config(state='normal')
            text_box.delete('1.0', tk.END)
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE, 'r', encoding='utf-8') as f:
                    text_box.insert('1.0', f.read())
                text_box.see(tk.END)
            else:
                text_box.insert('1.0', "에러 로그 없음")
            text_box.config(state='disabled')

        def clear_log():
            if messagebox.askyesno("초기화", "에러 로그를 삭제하시겠습니까?"):
                if os.path.exists(LOG_FILE):
                    os.remove(LOG_FILE)
                refresh()

        def open_file():
            import subprocess
            if os.path.exists(LOG_FILE):
                subprocess.Popen(['notepad.exe', LOG_FILE])

        tk.Button(btn_frame, text="🔄 새로고침", font=("Consolas", fs(8)),
                  fg=TEXT, bg="#1e1e2e", relief='flat', bd=0, cursor='hand2',
                  command=refresh).pack(side='right', padx=px(2))
        tk.Button(btn_frame, text="📝 메모장", font=("Consolas", fs(8)),
                  fg=TEXT, bg="#1e1e2e", relief='flat', bd=0, cursor='hand2',
                  command=open_file).pack(side='right', padx=px(2))
        tk.Button(btn_frame, text="🗑 로그 삭제", font=("Consolas", fs(8)),
                  fg="#ff6666", bg="#1e1e2e", relief='flat', bd=0, cursor='hand2',
                  command=clear_log).pack(side='right', padx=px(2))

        # 텍스트 박스
        frame = tk.Frame(win, bg=PANEL)
        frame.pack(fill='both', expand=True, padx=px(10), pady=(0, px(10)))

        text_box = tk.Text(frame, font=("Consolas", fs(8)), bg=PANEL, fg="#ff9999",
                           insertbackground=TEXT, relief='flat', bd=0,
                           wrap='word', state='disabled')
        sb = ttk.Scrollbar(frame, orient='vertical', command=text_box.yview)
        text_box.configure(yscrollcommand=sb.set)
        text_box.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        refresh()

    def _open_wishlist(self):
        """독점 차량 목록 관리 창"""
        win = tk.Toplevel(self.root)
        win.title("⭐ 독점 차량 목록")
        win.geometry(f"{self.px(420)}x{self.px(500)}")
        win.configure(bg="#0a0a0f")
        win.resizable(False, True)

        PANEL = "#12121a"; ACCENT = "#00d4ff"; TEXT = "#e8e8f0"; MUTED = "#5a5a7a"
        fs, px = self.fs, self.px

        tk.Label(win, text="⭐ 독점 차량 목록",
                 font=("Consolas", fs(12), "bold"), fg="#ffcc00", bg="#0a0a0f"
                 ).pack(pady=(px(12), px(4)))
        tk.Label(win, text="당첨 시 ⭐로 강조 표시됩니다",
                 font=("Consolas", fs(8)), fg=MUTED, bg="#0a0a0f").pack()

        # 목록
        list_frame = tk.Frame(win, bg=PANEL)
        list_frame.pack(fill='both', expand=True, padx=px(12), pady=px(8))

        listbox = tk.Listbox(list_frame, font=("Consolas", fs(9)),
                             bg=PANEL, fg=TEXT, selectbackground="#1a3a5c",
                             relief='flat', bd=0, activestyle='none')
        sb = ttk.Scrollbar(list_frame, orient='vertical', command=listbox.yview)
        listbox.configure(yscrollcommand=sb.set)
        listbox.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        for item in self.wishlist:
            listbox.insert(tk.END, item)

        # 입력
        entry_frame = tk.Frame(win, bg="#0a0a0f")
        entry_frame.pack(fill='x', padx=px(12), pady=(0, px(4)))
        entry_var = tk.StringVar()
        entry = tk.Entry(entry_frame, textvariable=entry_var,
                         font=("Consolas", fs(9)), bg="#1e1e2e", fg=TEXT,
                         insertbackground=ACCENT, relief='flat', bd=4)
        entry.pack(side='left', fill='x', expand=True, padx=(0, px(4)))

        def add_item():
            name = entry_var.get().strip()
            if name and name not in self.wishlist:
                self.wishlist.append(name)
                listbox.insert(tk.END, name)
                save_wishlist(self.wishlist)
                entry_var.set("")

        def del_item():
            sel = listbox.curselection()
            if sel:
                name = listbox.get(sel[0])
                self.wishlist.remove(name)
                listbox.delete(sel[0])
                save_wishlist(self.wishlist)

        tk.Button(entry_frame, text="추가",
                  font=("Consolas", fs(9)), fg="#0a0a0f", bg=ACCENT,
                  relief='flat', bd=0, cursor='hand2',
                  command=add_item).pack(side='left')

        tk.Button(win, text="선택 삭제",
                  font=("Consolas", fs(9)), fg=TEXT, bg="#1e1e2e",
                  relief='flat', bd=0, cursor='hand2',
                  command=del_item).pack(pady=(0, px(8)))

        entry.bind('<Return>', lambda e: add_item())

        # 파일 열기 버튼
        def open_file():
            import subprocess
            if not os.path.exists(WISHLIST_FILE):
                save_wishlist(self.wishlist)
            subprocess.Popen(['notepad.exe', WISHLIST_FILE])

        def reload_file():
            self.wishlist = load_wishlist()
            listbox.delete(0, tk.END)
            for item in self.wishlist:
                listbox.insert(tk.END, item)
            self._refresh_table()

        btn_frame = tk.Frame(win, bg="#0a0a0f")
        btn_frame.pack(pady=(0, px(10)))
        tk.Button(btn_frame, text="📝 메모장으로 편집",
                  font=("Consolas", fs(9)), fg=TEXT, bg="#1e1e2e",
                  relief='flat', bd=0, cursor='hand2',
                  command=open_file).pack(side='left', padx=px(4))
        tk.Button(btn_frame, text="🔄 파일 새로고침",
                  font=("Consolas", fs(9)), fg=TEXT, bg="#1e1e2e",
                  relief='flat', bd=0, cursor='hand2',
                  command=reload_file).pack(side='left', padx=px(4))

    def _drag_select(self, key: str):
        """드래그로 특정 영역 선택"""
        labels = {
            "cr": "CR 영역", "car": "차량 영역",
            "col1_cr": "1열 CR", "col1_car": "1열 차량",
            "col2_cr": "2열 CR", "col2_car": "2열 차량",
            "col3_cr": "3열 CR", "col3_car": "3열 차량",
        }
        self.root.iconify()  # 트래커 창 최소화
        self.root.after(300, lambda: self._do_drag_select(key, labels.get(key, key)))

    def _do_drag_select(self, key: str, title: str):
        region = select_region_by_drag(title)
        self.root.deiconify()  # 트래커 창 복원
        if region and key in self.region_vars:
            for k, v in region.items():
                if k in self.region_vars[key]:
                    self.region_vars[key][k].set(str(v))

    def _save_hotkey(self):
        new_hotkey = self.hotkey_var.get().strip()
        if not new_hotkey:
            return
        self.config["hotkey"] = new_hotkey
        save_config(self.config)
        try:
            keyboard.unhook_all_hotkeys()
            keyboard.add_hotkey(new_hotkey, self._manual_capture)
            self.status_label.config(text=f"● 단축키: {new_hotkey}", fg="#00ff88")
            self.root.after(2000, lambda: self.status_label.config(text="● 대기중", fg="#5a5a7a"))
        except Exception as e:
            messagebox.showwarning("오류", f"단축키 등록 실패: {e}")

    def _save_regions(self):
        mode = self.spin_mode.get()
        cfg_key = "normal_regions" if mode == "일반" else "super_regions"
        self.config[cfg_key] = self._get_regions_from_ui()
        save_config(self.config)
        messagebox.showinfo("저장", "영역이 저장되었습니다.")

    def _preview_regions(self):
        regions = self._get_regions_from_ui()
        for key, region in regions.items():
            img = capture_region(region)
            cv2.imshow(f"미리보기: {key} (아무 키나 눌러 닫기)", img)
            cv2.waitKey(0)
            cv2.destroyAllWindows()

    def _register_hotkey(self):
        try:
            keyboard.add_hotkey(self.hotkey_var.get(), self._manual_capture)
        except Exception as e:
            print(f"단축키 등록 실패: {e}")

    def _manual_capture(self):
        self.root.after(0, self._do_capture)

    def _do_capture(self):
        try:
            self._do_capture_inner()
        except Exception as e:
            log_error("캡처 중 오류", e)
            self.status_label.config(text="● 오류 발생!", fg="#ff4444")
            self.root.after(2000, lambda: self.status_label.config(text="● 대기중", fg="#5a5a7a"))

    def _do_capture_inner(self):
        self.status_label.config(text="● 캡처중...", fg="#ffcc00")
        self.root.update()

        mode = self.spin_mode.get()
        regions = self._get_regions_from_ui()
        results = []

        if mode == "일반":
            # CR 로고 감지 → 있으면 CR 영역, 없으면 차량 영역만 읽기
            cr_img = capture_region(regions["cr"]) if "cr" in regions else None
            car_img = capture_region(regions["car"]) if "car" in regions else None

            cr_detected = cr_img is not None and has_cr_logo(cr_img)
            print(f"[CR 감지] {'있음' if cr_detected else '없음'}")
            if cr_detected:
                text = ocr_image(cr_img)
                if text:
                    results.append(text)
            elif car_img is not None:
                text = ocr_image(car_img)
                if text:
                    results.append(text)
        else:
            # 슈퍼: 3열 × CR 로고 감지로 분기
            for col in ["col1", "col2", "col3"]:
                cr_key  = f"{col}_cr"
                car_key = f"{col}_car"
                cr_img  = capture_region(regions[cr_key])  if cr_key  in regions else None
                car_img = capture_region(regions[car_key]) if car_key in regions else None

                if cr_img is not None and has_cr_logo(cr_img):
                    text = ocr_image(cr_img)
                else:
                    text = ocr_image(car_img) if car_img is not None else ""

                if text:
                    results.append(text)

        combined = ' | '.join(results) if results else "인식 실패"
        self.ocr_label.config(text=combined[:120])

        if mode == "슈퍼":
            # 슈퍼휠스핀: 각 열 결과를 따로 파싱해서 크레딧 합산
            total_credits = 0
            item_names = []
            for r in results:
                t = classify(r)
                if t == "크레딧":
                    total_credits += extract_credits(r)
                item_names.append(r)

            record = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "spin_type": "슈퍼휠스핀",
                "item_type": classify(combined),
                "item_name": combined[:80],
                "credits": total_credits,
            }
        else:
            item_type = classify(combined)
            credits = extract_credits(combined) if item_type == "크레딧" else 0
            record = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "spin_type": "일반휠스핀",
                "item_type": item_type,
                "item_name": combined[:80],
                "credits": credits,
            }

        save_record(record)
        self.records.append(record)
        self._insert_row(record)
        self._update_stats()

        self.status_label.config(text="● 기록 완료!", fg="#00ff88")
        self.root.after(2000, lambda: self.status_label.config(text="● 대기중", fg="#5a5a7a"))

    def _insert_row(self, record: dict):
        mode_emoji = "🌟" if "슈퍼" in str(record.get("spin_type", "")) else "🎡"
        type_emoji = {"차량": "🚗", "크레딧": "💰", "기타": "❓"}.get(record.get("item_type", ""), "❓")
        item_name = str(record.get("item_name") or "")[:80]

        # 위시리스트 매칭 확인
        is_wish = check_wishlist(item_name, self.wishlist)
        display_name = f"⭐ {item_name}" if is_wish else item_name

        iid = self.tree.insert('', 0, values=(
            record.get("timestamp", ""),
            f"{mode_emoji} {record.get('spin_type', '')}",
            f"{type_emoji} {record.get('item_type', '')}",
            display_name,
        ))
        if is_wish:
            self.tree.item(iid, tags=('wish',))

    def _setup_tree_tags(self):
        self.tree.tag_configure('wish', background='#2a1a00', foreground='#ffcc00')

    def _refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for r in reversed(self.records):
            self._insert_row(r)

    def _update_stats(self):
        total = len(self.records)
        cars = sum(1 for r in self.records if r.get("item_type") == "차량")
        credits_sum = sum(int(r.get("credits") or 0) for r in self.records)
        etc = sum(1 for r in self.records if r.get("item_type") == "기타")
        self.stat_vars["total"].set(str(total))
        self.stat_vars["cars"].set(str(cars))
        self.stat_vars["credits"].set(f"{credits_sum:,}")
        self.stat_vars["etc"].set(str(etc))

    def _export_excel(self):
        if not self.records:
            messagebox.showwarning("없음", "기록된 데이터가 없습니다.")
            return
        df = pd.DataFrame(self.records)
        fname = f"wheelspin_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        df.to_excel(fname, index=False)
        messagebox.showinfo("완료", f"저장됨: {fname}")

    def _clear_records(self):
        if messagebox.askyesno("초기화", "모든 기록을 삭제하시겠습니까?"):
            self.records = []
            if os.path.exists(SAVE_FILE):
                os.remove(SAVE_FILE)
            self._refresh_table()
            self._update_stats()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = WheelspinTracker()
    app.run()
