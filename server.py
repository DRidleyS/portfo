from flask import Flask, render_template, request
import csv

app = Flask(__name__)

@app.route("/", methods=['POST', 'GET'])
def home():
    '''
    This is the home route, the if statement is only used upon form submission
    '''
    if request.method == 'POST':
        data = request.form.to_dict()
        write_to_csv(data)
        return view_article("thanks")

    return render_template("index.html")

@app.route("/<article_name>")
def view_article(article_name):
    if article_name == "thanks":
        return render_template("thanks.html")
    else:
        return render_template("index.html")

def write_to_csv(data):
    with open("database.csv", mode='a') as database:
        name = data["name"]
        email = data["email"]
        message = data["message"]
        csv_writer = csv.writer(database, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
        csv_writer.writerow([name, email, message])

if __name__ == '__main__':
    app.run(debug=True)