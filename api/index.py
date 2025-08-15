import json

from flask import Flask
from flask import request
app = Flask(__name__)

@app.route('/')
def home():
    return 'Hello, World!'


@app.route("/privacy_policy")
def privacy_policy():
    with open("./privacy_policy.html", "rb") as file:
        privacy_policy_html = file.read()
    return privacy_policy_html

@app.route("/webhook", methods = ["GET", "POST" ])
def webhook():
    if request.method == "POST":
        try:
            pass
        except :
            pass
        return "<p>This is POST Request, Hello Webhook !< /p>"
    if request.method == "GET":
        hub_mode = request.args.get("hub.mode")
        hub_challenge = request.args.get("hub.challenge")
        hub_verify_token = request.args.get("hub.verify_token")
        if hub_challenge:
            return hub_challenge
        else:
            return "<p>This is GET Request, Hello Webhook !< /p>"

print(json.dumps(request.get_json(), indent=4))