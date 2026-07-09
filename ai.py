from openai import OpenAI
import base64
import io

client = OpenAI()

def analyze_image(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    img_base64 = base64.b64encode(buffer.getvalue()).decode()

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Give actionable suggestions about this screen area."},
                {"type": "input_image", "image_base64": img_base64}
            ]
        }]
    )

    return response.output_text