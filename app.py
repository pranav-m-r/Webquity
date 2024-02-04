from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from forex_python.converter import CurrencyRates
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

import csv
import datetime
import pytz
import requests
import urllib
import uuid


def apology(message, code=400):
    """Render message as an apology to user"""

    flash(message.title() + " (Error Code: " + str(code) + ")")
    if session.get("username") is None:
        session["username"] = ""
    return render_template(request.path + ".html", username=session["username"])


def login_required(f):
    """
    Decorate routes to require login

    https://flask.palletsprojects.com/en/latest/patterns/viewdecorators/
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            session["username"] = ""
            return redirect("/login")
        return f(*args, **kwargs)

    return decorated_function


def lookup(symbol):
    """Look up quote for symbol"""

    # Prepare API request
    symbol = symbol.upper()
    end = datetime.datetime.now(pytz.timezone("US/Eastern"))
    start = end - datetime.timedelta(days=7)

    # Yahoo Finance API
    url = (
        f"https://query1.finance.yahoo.com/v7/finance/download/{urllib.parse.quote_plus(symbol)}"
        f"?period1={int(start.timestamp())}"
        f"&period2={int(end.timestamp())}"
        f"&interval=1d&events=history&includeAdjustedClose=true"
    )

    # Query API
    try:
        response = requests.get(
            url,
            cookies={"session": str(uuid.uuid4())},
            headers={"Accept": "*/*", "User-Agent": "python-requests"},
        )
        response.raise_for_status()

        # CSV header: Date,Open,High,Low,Close,Adj Close,Volume
        quotes = list(csv.DictReader(response.content.decode("utf-8").splitlines()))

        price = CurrencyRates().convert("USD", "INR", round(float(quotes[-1]["Adj Close"]), 2))
        return {"price": price, "symbol": symbol}
    except (KeyError, IndexError, requests.RequestException, ValueError):
        return None


def inr(value):
    """Format value as INR"""
    return f"₹{value:,.2f}"


# Configure application
app = Flask(__name__)

# Custom filter
app.jinja_env.filters["inr"] = inr

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///database.db")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    sum = 0
    param = []

    # Create list of dictionaries required for the table
    for row in db.execute("SELECT symbol, SUM(total) AS total, SUM(shares) AS shares FROM history WHERE userid=? GROUP BY symbol", session["user_id"]):
        if row["shares"] != 0:
            param.append(row)
            param[len(param) - 1]["price"] = lookup(row["symbol"])["price"]
            sum += param[len(param) - 1]["price"] * row["shares"]
            param[len(param) - 1]["oldprice"] = row["total"]/row["shares"]

    # Get user specific data
    usrdata = db.execute("SELECT cash, deposit, withdraw FROM users WHERE id = ?", session["user_id"])[0]
    session["balance"] = float(usrdata["cash"])
    session["deposit"] = float(usrdata["deposit"])
    session["withdraw"] = float(usrdata["withdraw"])
    session["sum"] = sum

    return render_template("index.html", rows=param, balance=session["balance"], username=session["username"],
                           deposit=session["deposit"], withdraw=session["withdraw"], sum=sum)


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""

    rows = db.execute("SELECT symbol, price, shares, time FROM history WHERE userid=? ORDER BY id DESC", session["user_id"])

    # Retrieve history and create the view with user-specific data
    return render_template("history.html", rows=rows, username=session["username"], sum=session["sum"],
                           balance=session["balance"], deposit=session["deposit"], withdraw=session["withdraw"])


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # Ensure username was submitted
        if not str(request.form.get("username")).isalnum():
            return apology("invalid username", 400)

        # Ensure password was submitted
        elif not str(request.form.get("password")).isascii():
            return apology("invalid password", 400)

        # Ensure password was confirmed
        elif not str(request.form.get("confirmation")).isascii():
            return apology("invalid password", 400)

        # Ensure password and confirmation are the same
        elif request.form.get("password") != request.form.get("confirmation"):
            return apology("password and confirmation do not match", 400)

        # Ensure username does not already exist
        elif len(rows) != 0:
            return apology("username already exists", 400)

        # Check for username specifications
        elif len(str(request.form.get("username"))) < 8 or len(str(request.form.get("username"))) > 16:
            return apology("username must contain 8-16 characters", 400)

        # Check for password specifications
        flag1 = False
        flag2 = False
        flag3 = False
        for i in str(request.form.get("password")):
            if i.isalpha():
                flag1 = True
            elif i.isdigit():
                flag2 = True
            else:
                flag3 = True
        if not (flag1 and flag2 and flag3):
            return apology("password must contain atleast one alphabet, number and special character", 400)
        elif len(str(request.form.get("password"))) < 8 or len(str(request.form.get("password"))) > 16:
            return apology("password must contain 8-16 characters", 400)

        # Insert new user into database
        db.execute(
            "INSERT INTO users (username, hash) VALUES (?, ?)", request.form.get(
                "username"), generate_password_hash(request.form.get("password"))
        )

        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]
        session["username"] = rows[0]["username"]
        flash("Welcome " + session["username"] + "!")

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        # Ensure username was submitted
        if not str(request.form.get("username")).isalnum():
            return apology("invalid username", 403)

        # Ensure password was submitted
        elif not str(request.form.get("password")).isascii():
            return apology("invalid password", 403)

        # Query database for username
        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(
            rows[0]["hash"], request.form.get("password")
        ):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]
        session["username"] = rows[0]["username"]
        flash("Welcome " + session["username"] + "!")

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/search", methods=["GET", "POST"])
@login_required
def search():
    """Search up stock information."""

    if request.method == "POST":

        # Check if symbol is valid
        if str(request.form.get("symbol")).isalnum():
            quote = lookup(request.form.get("symbol"))

            # Get charts from stockcharts.com for the symbol
            if quote:
                url1 = "https://stockcharts.com/c-sc/sc?s=" + quote["symbol"] + "&p=D&b=3&g=0&i=0"
                url2 = "https://stockcharts.com/c-sc/sc?s=" + quote["symbol"] + "&p=W&b=3&g=0&i=0"
                return render_template("search.html", quote=quote, username=session["username"], url1=url1, url2=url2)
            else:
                return apology("invalid symbol", 400)
        else:
            return apology("invalid symbol", 400)

    else:
        return render_template("search.html", quote="", username=session["username"])


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""

    if request.method == "POST":

        # Check for invalid entries
        if str(request.form.get("symbol")).isalnum():
            quote = lookup(request.form.get("symbol"))
        else:
            return apology("invalid symbol", 400)
        try:
            shares = float(request.form.get("shares"))
        except ValueError:
            return apology("invalid entry for shares", 400)
        if not quote:
            return apology("invalid symbol", 400)
        elif shares <= 0 or shares % 1 != 0:
            return apology("invalid number of shares", 400)

        # Check balance
        cash = quote["price"] * shares
        if cash > session["balance"]:
            return apology("insufficient balance", 400)

        # Update the database
        db.execute("INSERT INTO history (userid, symbol, price, shares, time, total) VALUES (?, ?, ?, ?, ?, ?)",
                   session["user_id"], quote["symbol"], quote["price"], shares, datetime.datetime.now(), quote["price"]*shares)
        db.execute("UPDATE users SET cash=? WHERE id=?", session["balance"] - cash, session["user_id"])
        row = {"symbol": quote["symbol"], "price": quote["price"], "shares": int(shares)}
        balance = session["balance"]
        session["balance"] -= cash

        flash("Bought Stocks Successfully")
        return render_template("transaction.html", row=row, balance=balance, currbalance=session["balance"], username=session["username"])

    else:
        return render_template("buy.html", username=session["username"])


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""

    if request.method == "POST":

        # Check for invalid entries
        if str(request.form.get("symbol")).isalnum():
            quote = lookup(request.form.get("symbol"))
        else:
            return apology("invalid symbol", 400)
        try:
            shares = float(request.form.get("shares"))
        except ValueError:
            return apology("invalid entry for shares", 400)
        if not quote:
            return apology("invalid symbol", 400)
        if shares <= 0 or shares % 1 != 0:
            return apology("invalid number of shares", 400)
        elif db.execute("SELECT SUM(shares) AS shares FROM history WHERE userid=? AND symbol=? GROUP BY symbol", session["user_id"], quote["symbol"])[0]["shares"] < shares:
            return apology("insufficient shares", 400)

        # Update the database
        cash = quote["price"] * shares
        session["balance"] = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]
        db.execute("INSERT INTO history (userid, symbol, price, shares, time, total) VALUES (?, ?, ?, ?, ?, ?)",
                   session["user_id"], quote["symbol"], quote["price"], shares * (-1), datetime.datetime.now(), quote["price"]*shares*(-1))
        db.execute("UPDATE users SET cash=? WHERE id=?", session["balance"] + cash, session["user_id"])
        row = {"symbol": quote["symbol"], "price": quote["price"], "shares": int(shares)}
        balance = session["balance"]
        session["balance"] += cash

        flash("Sold Stocks Successfully")
        return render_template("transaction.html", row=row, balance=balance, currbalance=session["balance"], username=session["username"])

    else:
        symbols = db.execute("SELECT symbol FROM history WHERE userid=? GROUP BY symbol", session["user_id"])
        return render_template("sell.html", rows=symbols, username=session["username"])


@app.route("/deposit", methods=["GET", "POST"])
@login_required
def deposit():
    """Add cash to account"""

    if request.method == "POST":
        cash = str(request.form.get("amount"))

        # Check for invalid entries
        if not cash.isnumeric():
            return apology("invalid amount", 400)
        cash = float(cash)
        if cash <= 0:
            return apology("invalid amount", 400)

        # Update the database
        db.execute("UPDATE users SET cash=?, deposit=? WHERE id=?", session["balance"] + cash,
                   session["deposit"] + cash, session["user_id"])
        row = {"symbol": "Cash Deposited", "price": cash, "shares": 0}
        balance = session["balance"]
        session["balance"] += cash
        session["deposit"] += cash

        flash("Cash Deposited Successfully")
        return render_template("transaction.html", row=row, balance=balance, currbalance=session["balance"], username=session["username"])

    else:
        return render_template("deposit.html", username=session["username"])


@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():
    """Add cash to account"""

    if request.method == "POST":

        # Check for invalid entries
        cash = str(request.form.get("amount"))
        if not cash.isnumeric():
            return apology("invalid amount", 400)
        cash = float(cash)
        if cash <= 0:
            return apology("invalid amount", 400)

        # Update the database
        db.execute("UPDATE users SET cash=?, withdraw=? WHERE id=?", session["balance"] - cash,
                   session["withdraw"] + cash, session["user_id"])
        row = {"symbol": "Cash Withdrawn", "price": cash, "shares": 0}
        balance = session["balance"]
        session["balance"] -= cash
        session["withdraw"] += cash

        flash("Cash Withdrawn Successfully")
        return render_template("transaction.html", row=row, balance=balance, currbalance=session["balance"], username=session["username"])

    else:
        return render_template("withdraw.html", username=session["username"])


@app.route("/password", methods=["GET", "POST"])
def password():
    """Change user's password"""

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # Ensure password was submitted
        if not str(request.form.get("password")).isascii():
            return apology("invalid password", 400)

        # Ensure password was confirmed
        elif not str(request.form.get("confirmation")).isascii():
            return apology("invalid password", 400)

        # Ensure password and confirmation are the same
        elif request.form.get("password") != request.form.get("confirmation"):
            return apology("password and confirmation do not match", 400)

        # Check for password specifications
        flag1 = False
        flag2 = False
        flag3 = False
        for i in str(request.form.get("password")):
            if i.isalpha():
                flag1 = True
            elif i.isdigit():
                flag2 = True
            else:
                flag3 = True
        if not (flag1 and flag2 and flag3):
            return apology("password must contain atleast one alphabet, number and special character", 400)
        elif len(str(request.form.get("password"))) < 8 or len(str(request.form.get("password"))) > 16:
            return apology("password must contain 8-16 characters", 400)

        # Change password in the database
        db.execute("UPDATE users SET hash=? WHERE id=?", generate_password_hash(request.form.get("password")), session["user_id"])
        flash("Changed Password Successfully")

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("password.html", username=session["username"])
