# 🎡 Forza Wheelspin Tracker

포르자 호라이즌 휠스핀 결과를 자동으로 인식하고 기록해주는 툴

---

## 📋 Requirements

- Python 3.10 이상
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (설치 시 Korean 언어팩 체크 필요)

```
pip install pillow pytesseract mss opencv-python pandas openpyxl keyboard
```

---

## 🚀 실행 방법

`실행.bat` 더블클릭

---

## ⚙️ 초기 설정

1. 모드 선택 — **일반** 또는 **슈퍼** 휠스핀
2. 각 영역 옆 **✥ 버튼** 클릭 후 마우스 드래그로 캡처 영역 지정
3. **영역 저장** 클릭
4. 단축키 기본값은 **F9** (변경 가능)

> `wheelspin_config.json` 의 좌표값은 3440x1440 울트라와이드 기준 예시입니다. 본인 해상도에 맞게 재설정하세요.

---

## 🎮 사용 방법

1. 게임에서 휠스핀을 돌려 결과 화면이 뜨면
2. **F9** 누르기
3. 자동으로 화면 인식 후 기록

---

## ✨ 주요 기능

- 일반 / 슈퍼 휠스핀 모드 토글
- 차량 / 크레딧 자동 구분 (CR 로고 감지)
- 크레딧 합계 자동 계산
- 독점 차량 당첨 시 강조 표시 (`exclusive_cars.txt` 에 차량명 입력)
- 엑셀 내보내기
- 에러 로그 뷰어

---

## 📁 파일 구성

| 파일 | 설명 |
|------|------|
| `wheelspin_tracker.py` | 메인 프로그램 |
| `실행.bat` | 실행 파일 |
| `exclusive_cars.txt` | 독점 차량 목록 (한 줄에 하나씩) |
| `wheelspin_config.json` | 캡처 영역 설정 예시 |
| `설명서.txt` | 상세 사용 설명서 |

---

## ⚠️ 참고

- OCR 특성상 짧은 차량명(예: F1)은 가끔 인식 실패할 수 있음
- 단축키가 작동하지 않을 경우 관리자 권한으로 실행
