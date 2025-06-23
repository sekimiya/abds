from card_ocr import crop_sp_section, extract_sp_details_from_image, sanitize_filename
import os
import json

api_key = open('APIkey.txt').read().strip()
card_number = 'FQ01-004'
card_name = 'ジム・カスタム'
series_name = 'FQ01'
back_image_url = 'https://www.gundam-ab.com/images/cardlist/card/FQ01-004_b.jpg?v8'
results_dir = 'ocr_results_debug'

os.makedirs(results_dir, exist_ok=True)

print('--- SP画像切り抜きテスト ---')
sp_image_b64 = crop_sp_section(back_image_url, save_dir=results_dir, card_number=card_number, card_name=card_name)
if sp_image_b64:
    print('sp_image_b64: OK (length = {})'.format(len(sp_image_b64)))
else:
    print('sp_image_b64: None')
    with open(os.path.join(results_dir, 'sp_crop_error.json'), 'w', encoding='utf-8') as f:
        json.dump({'error': 'SP画像切り抜き失敗'}, f, ensure_ascii=False, indent=2)
    exit(1)

data_url = f"data:image/jpeg;base64,{sp_image_b64}"

print('--- SP OCR APIテスト ---')
sp_result = extract_sp_details_from_image(data_url, api_key)
if not sp_result or not isinstance(sp_result, str) or len(sp_result.strip()) == 0:
    print('sp_result: None or empty')
    with open(os.path.join(results_dir, 'sp_ocr_error.json'), 'w', encoding='utf-8') as f:
        json.dump({'error': 'SP OCRレスポンスが空'}, f, ensure_ascii=False, indent=2)
    exit(1)
else:
    print('sp_result:', sp_result[:500])

# 保存処理
safe_number = sanitize_filename(card_number)
safe_name = sanitize_filename(card_name)
safe_series = sanitize_filename(series_name)
sp_raw_result_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}_sp_raw.json")
sp_parsed_result_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}_sp.json")

with open(sp_raw_result_file, 'w', encoding='utf-8') as f:
    f.write(sp_result)
print(f"✓ SP生データ保存: {sp_raw_result_file}")

sp_json_str = sp_result
if "```json" in sp_result:
    sp_json_str = sp_result.split("```json")[1].split("```", 1)[0].strip()
elif "```" in sp_result:
    sp_json_str = sp_result.split("```", 1)[1].strip()
try:
    sp_details = json.loads(sp_json_str)
    with open(sp_parsed_result_file, 'w', encoding='utf-8') as f:
        json.dump(sp_details, f, ensure_ascii=False, indent=2)
    print(f"✓ SP詳細OCRパース済みデータ保存: {sp_parsed_result_file}")
except Exception as e:
    print(f"⚠ SP詳細OCR結果のパース失敗: {e}") 