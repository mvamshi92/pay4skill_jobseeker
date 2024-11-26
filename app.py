import os
import time
import google.generativeai as genai
from google.cloud import storage
from flask import Flask, render_template, request, redirect, url_for
import json
import re
from PyPDF2 import PdfReader

# Set up Flask app
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'pdf'}

# Set up Google Cloud Service Account Key
service_account_path = "service_account.json"  # Replace with your service account JSON file path
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = service_account_path

# Set up the Gemini API key
genai.configure(api_key="GEMINI_API")  # Replace with your Gemini API key

# Function to check allowed file extensions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def extract_text_from_pdf(file_path):
    """
    Extracts text from a PDF file using PyPDF2.

    :param file_path: Path to the PDF file
    :return: Extracted text
    """
    try:
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text()
        return text
    except Exception as e:
        print(f"An error occurred while extracting text from PDF: {e}")
        return None

def upload_to_gcs(local_file_path, bucket_name, destination_blob_name):
    """
    Uploads a file to Google Cloud Storage.

    :param local_file_path: Path to the file on your local machine
    :param bucket_name: Name of the GCS bucket
    :param destination_blob_name: Target path/name in the bucket
    :return: Public URL of the uploaded file
    """
    try:
        # Create a Cloud Storage client
        client = storage.Client()

        # Access the target bucket
        bucket = client.bucket(bucket_name)

        # Create a blob (object) and upload the file
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(local_file_path)

        # Make the file publicly accessible
        blob.make_public()

        # Return the public URL
        return blob.public_url
    except Exception as e:
        print(f"An error occurred: {e}")
        return blob.public_url

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(request.url)
    
    file = request.files['file']
    
    if file.filename == '' or not allowed_file(file.filename):
        return redirect(request.url)
    
    # Save the file locally
    local_file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.save(local_file_path)

    # Upload the file to Google Cloud Storage
    bucket_name = "GSS_BUCKET"  # Replace with your GCS bucket name
    destination_blob_name = file.filename
    public_url = upload_to_gcs(local_file_path, bucket_name, destination_blob_name)
    
    if not public_url:
        return "Failed to upload the file to Google Cloud Storage.", 500

    # Extract text from the uploaded PDF
    pdf_text = extract_text_from_pdf(local_file_path)
    if not pdf_text:
        return "Failed to extract text from the PDF.", 500

    # Create the model and generate the analysis
    generation_config = {
        "temperature": 1,
        "top_p": 0.95,
        "top_k": 40,
        "max_output_tokens": 8192,
        "response_mime_type": "text/plain",
    }

    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        generation_config=generation_config,
    )

    chat_session = model.start_chat(
        history=[
            {
                "role": "user",
                "parts": [
                    "Analyze the provided resume text and generate a JSON response with the following format:\n\n"
                    "{\n"
                    "  \"resumeurl\": \"<PUBLIC_URL>\",\n"
                    "  \"overallExperience\": 8,\n"
                    "  \"location\": \"hyderabad\",\n"
                    "  \"email\": \"TEST@gmail.com\",\n"
                    "  \"phone\": \"1234521\",\n"
                    "  \"name\": \"vamsi\",\n"
                    "  \"skills\": [\n"
                    "    {\n"
                    "      \"skill\": \"Python\",\n"
                    "      \"rating\": 7\n"
                    "    },\n"
                    "    {\n"
                    "      \"skill\": \"JavaScript\",\n"
                    "      \"rating\": 9\n"
                    "    }\n"
                    "  ],\n"
                    "  \"experience\": [\n"
                    "    {\n"
                    "      \"company\": \"\",\n"
                    "      \"experience\": 2\n"
                    "    },\n"
                    "    {\n"
                    "      \"company\": \"\",\n"
                    "      \"experience\": 3\n"
                    "    }\n"
                    "  ],\n"
                    "  \"hasCertification\": true,\n"
                    "  \"education\": \"B.Tech\"\n"
                    "}\n"
                ],
            },
            {
                "role": "user",
                "parts": [pdf_text],  # Provide extracted text only for analysis
            },
        ]
    )

    response = chat_session.send_message(
        "Analyze the provided text and provide a JSON response as described. Include the public URL in the JSON but do not use the public URL for analytics."
    )

    # Extract the JSON part from the response
    match = re.search(r'\{.*\}', response.text, re.DOTALL)
    if match:
        json_response = json.loads(match.group(0))  # Convert JSON string to Python dict
        # Add the public URL to the JSON response
        json_response["resumeurl"] = public_url
    else:
        json_response = {"error": "No valid JSON found in the response", "resumeurl": public_url}

    # Pass the JSON to the result template
    return render_template('result.html', result=json_response)

if __name__ == '__main__':
    app.run(debug=True)
