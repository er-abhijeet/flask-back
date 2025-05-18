from flask import Flask, request, jsonify
from flask_cors import CORS  # Import CORS
import os
import json
import re
import io
from pdf2image import convert_from_path
from PIL import Image
import google.generativeai as genai
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
CORS(app)

# Configure upload folder
UPLOAD_FOLDER = 'Uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Configure Gemini API (use environment variable for security)
key=os.environ.get("gemini_api")
genai.configure(api_key=os.getenv("GEMINI_API_KEY", key))

# Function to call Gemini with an image for medical term extraction
def extract_medical_terms_with_gemini_image(image_data, mime_type="image/jpeg"):
    prompt = """
    You are a medical data extraction assistant. The attached image is a medical report (or a page from a medical report PDF). Identify all medical terms (e.g., hemoglobin, creatinine, blood sugar) and their associated values (numeric or textual, including units if present). Format the output as a JSON object with two keys:
    - "key_value_pairs": Non-medical key-value pairs (e.g., patient name, age).
    - "extracted_tests": Medical terms and their values (e.g., hemoglobin: 13.5 g/dL).
    Do not use hardcoded patterns; rely on your understanding of medical terminology. If a term's value is unclear, skip it. Do not hallucinate values or tests that are not explicitly mentioned in the image. If a value is a reference range (e.g., '3.5-5.5'), only include it if no actual value is present. Ensure the output is valid JSON.

    Output format:
    {
        "key_value_pairs": {},
        "extracted_tests": {}
    }
    """

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(
            [
                prompt,
                {
                    "mime_type": mime_type,
                    "data": image_data
                }
            ],
            generation_config={
                "temperature": 0.3,
                "max_output_tokens": 1000
            }
        )
        print("Gemini Response Text:", response.text)
        
        # Extract JSON content between ```json and ```
        json_match = re.search(r'```json\n([\s\S]*?)\n```', response.text)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            json_str = response.text.strip()
        print("JSON String to Parse:", json_str)  # Add this line
        extracted_data = json.loads(json_str)
        return extracted_data
    except json.JSONDecodeError as e:
        print(f"Error parsing Gemini response as JSON: {e}")
        print("Raw Response:", response.text)
        return {"key_value_pairs": {}, "extracted_tests": {}}
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return {"key_value_pairs": {}, "extracted_tests": {}}

# app.py (relevant changes)
def convert_pdf_to_images(pdf_path):
    try:
        images = convert_from_path(pdf_path)  # No poppler_path, assume system-wide install
        print(f"Extracted {len(images)} pages from PDF")
        return images
    except Exception as e:
        print(f"Error converting PDF to images: {e}")
        return []

# Function to process an uploaded file (image or PDF)
def process_uploaded_file(uploaded_file_path):
    file_extension = os.path.splitext(uploaded_file_path)[1].lower()
    all_results = []

    if file_extension in ['.pdf']:
        images = convert_pdf_to_images(uploaded_file_path)
        if not images:
            print("Failed to extract images from PDF.")
            return [{"page": 1, "data": {"key_value_pairs": {}, "extracted_tests": {}}}]
        
        for idx, image in enumerate(images):
            print(f"Processing page {idx + 1} of PDF")
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format="JPEG")
            image_data = img_byte_arr.getvalue()
            result = extract_medical_terms_with_gemini_image(image_data, mime_type="image/jpeg")
            all_results.append({"page": idx + 1, "data": result})
    elif file_extension in ['.jpg', '.jpeg', '.png']:
        with open(uploaded_file_path, "rb") as image_file:
            image_data = image_file.read()
        result = extract_medical_terms_with_gemini_image(image_data, mime_type="image/jpeg")
        all_results.append({"page": 1, "data": result})
    else:
        raise ValueError(f"Unsupported file type: {file_extension}. Please upload a PDF, JPEG, or PNG file.")

    return all_results

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if file:
        filename = file.filename
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        try:
            results = process_uploaded_file(file_path)
            if not results or (len(results) == 1 and not results[0]["data"]["key_value_pairs"] and not results[0]["data"]["extracted_tests"]):
                return jsonify({"error": "Failed to extract data from the file. Ensure the file contains readable medical report data."}), 500
            
            if len(results) == 1:
                final_output = results[0]["data"]
            else:
                combined_key_value_pairs = {}
                combined_extracted_tests = {}
                for result in results:
                    page_data = result["data"]
                    combined_key_value_pairs.update(page_data["key_value_pairs"])
                    combined_extracted_tests.update(page_data["extracted_tests"])
                final_output = {
                    "key_value_pairs": combined_key_value_pairs,
                    "extracted_tests": combined_extracted_tests
                }
            
            return jsonify({"data": final_output})
        except Exception as e:
            return jsonify({"error": f"Processing failed: {str(e)}"}), 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))  # Use Render's PORT or default to 5000
    app.run(host='0.0.0.0', port=port)