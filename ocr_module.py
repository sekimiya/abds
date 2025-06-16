import cv2
import numpy as np
import pytesseract
from PIL import Image
import requests
from io import BytesIO
import openai
import base64
import io
import os

class CardOCR:
    def __init__(self, api_key_path):
        self.api_key = self._read_api_key(api_key_path)
        openai.api_key = self.api_key
        # Tesseractの設定
        self.config = '--psm 6 --oem 3 -l jpn'
        
    def _read_api_key(self, file_path):
        with open(file_path, 'r') as f:
            return f.read().strip()

    def _encode_image_to_base64(self, path):
        with Image.open(path) as img:
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def preprocess_image(self, image):
        """画像の前処理を行う"""
        # グレースケール変換
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # ノイズ除去
        denoised = cv2.fastNlMeansDenoising(gray)
        
        # 二値化
        _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # コントラスト強調
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        enhanced = clahe.apply(gray)
        
        return enhanced

    def extract_text_regions(self, image):
        """テキスト領域を抽出する"""
        # エッジ検出
        edges = cv2.Canny(image, 50, 150)
        
        # 輪郭検出
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # テキスト領域の抽出
        text_regions = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w > 20 and h > 20:  # 小さすぎる領域は除外
                text_regions.append((x, y, w, h))
        
        return text_regions

    def read_card_info(self, image_url):
        """カード画像から情報を読み取る"""
        try:
            # 画像のダウンロード（User-Agent付与）
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(image_url, headers=headers)
            print(f"ステータス: {response.status_code}")
            print(f"Content-Type: {response.headers.get('Content-Type')}")
            print(f"画像データサイズ: {len(response.content)} bytes")
            try:
                image = Image.open(BytesIO(response.content))
            except Exception as e:
                print(f"Pillowで画像を開けません: {e}")
                return None
            image = np.array(image)
            
            # 画像の前処理
            processed_image = self.preprocess_image(image)
            
            # テキスト領域の抽出
            text_regions = self.extract_text_regions(processed_image)
            
            # 各領域からテキストを読み取り
            card_info = {
                'name': '',
                'cost': '',
                'power': '',
                'text': ''
            }
            
            for x, y, w, h in text_regions:
                roi = processed_image[y:y+h, x:x+w]
                text = pytesseract.image_to_string(roi, config=self.config)
                
                # テキストの位置に基づいて情報を分類
                if y < image.shape[0] * 0.2:  # 上部
                    card_info['name'] = text.strip()
                elif y < image.shape[0] * 0.4:  # 上部中央
                    if 'コスト' in text:
                        card_info['cost'] = text.strip()
                elif y < image.shape[0] * 0.6:  # 中央
                    if 'パワー' in text:
                        card_info['power'] = text.strip()
                else:  # 下部
                    card_info['text'] += text.strip() + '\n'
            
            return card_info
            
        except Exception as e:
            print(f"OCR Error: {str(e)}")
            return None

    def analyze_card(self, image_url):
        """カードの詳細分析を行う"""
        card_info = self.read_card_info(image_url)
        if not card_info:
            return None
            
        # カード情報の解析
        analysis = {
            'basic_info': card_info,
            'type': self.detect_card_type(card_info['text']),
            'rarity': self.detect_rarity(card_info['text']),
            'effects': self.extract_effects(card_info['text'])
        }
        
        return analysis

    def detect_card_type(self, text):
        """カードタイプを検出"""
        if 'モビルスーツ' in text:
            return 'MS'
        elif 'パイロット' in text:
            return 'PL'
        return 'Unknown'

    def detect_rarity(self, text):
        """レアリティを検出"""
        rarity_patterns = {
            'SN': 'SN',
            'PR': 'PR',
            'FQ': 'FQ',
            'UT': 'UT',
            'LX': 'LX',
            'A': 'A',
            'U': 'U',
            'P': 'P',
            'M': 'M',
            'R': 'R',
            'C': 'C',
            'SEC': 'SEC'
        }
        
        for pattern, rarity in rarity_patterns.items():
            if pattern in text:
                return rarity
        return 'Unknown'

    def extract_effects(self, text):
        """効果を抽出"""
        effects = []
        lines = text.split('\n')
        
        for line in lines:
            if any(keyword in line for keyword in ['効果', '能力', '特殊効果']):
                effects.append(line.strip())
                
        return effects

    def extract_text(self, image_path):
        """
        画像からテキストを抽出するメソッド
        
        Args:
            image_path (str): 画像ファイルのパス
            
        Returns:
            str: 抽出されたテキスト
        """
        try:
            base64_image = self._encode_image_to_base64(image_path)
            
            response = openai.ChatCompletion.create(
                model="gpt-4-vision-preview",
                messages=[
                    {"role": "system", "content": "あなたは画像内の文字を読み取って、分かりやすくテキストで返すOCRアシスタントです。"},
                    {"role": "user", "content": [
                        {"type": "text", "text": "この画像内の文字をすべて読み取って、整ったテキストとして出力してください。"},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/png;base64,{base64_image}",
                        }},
                    ]}
                ],
                max_tokens=2048,
            )
            
            return response['choices'][0]['message']['content']
        except Exception as e:
            raise Exception(f"テキスト抽出中にエラーが発生しました: {str(e)}")

# テスト用のコード
if __name__ == "__main__":
    # テスト実行
    ocr = CardOCR('APIKey.txt')
    try:
        result = ocr.extract_text('card_sample.png')
        print("読み取り結果:")
        print(result)
    except Exception as e:
        print(f"エラー: {str(e)}") 