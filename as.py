from dotenv import load_dotenv
import os
load_dotenv()
key=os.environ.get("gemini_api")
print(key)