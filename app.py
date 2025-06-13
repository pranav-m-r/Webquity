import firebase_admin
from firebase_admin import credentials, firestore
from google.api_core import exceptions as google_exceptions

from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_session import Session
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

import datetime
import pytz
import requests
import urllib
import os
from dotenv import load_dotenv


# --- Firebase Initialization ---
try:
    cred = credentials.Certificate("firebase.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    print(f"FATAL: Failed to initialize Firebase Admin SDK: {e}")
    db = None
# --- End Firebase Initialization ---


request_session = requests.Session()
request_session.headers.update({
    "Accept": "*/*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
})

load_dotenv()
api_key = os.getenv("API_KEY")


def apology(message, code=400):
    """Render message as an apology to user"""

    flash(message.title() + " (Error Code: " + str(code) + ")")
    username_for_template = session.get("username", "")
    if not username_for_template and "user_id" in session: # Attempt to get username if only ID exists
        try:
            if db:
                user_doc = db.collection("users").document(session["user_id"]).get()
                if user_doc.exists:
                    username_for_template = user_doc.to_dict().get("username", "")
        except Exception:
            pass # Ignore if db access fails here

    # Try to render the current endpoint's template, or redirect to index on failure/no endpoint
    # This logic attempts to re-render the page where the error occurred.
    # It's a simplified approach; complex pages might need more specific context.
    if request.endpoint and request.endpoint != "static":
        template_name = request.endpoint + ".html"
        try:
            extra_context = {}
            # Provide minimal context for common pages if an error occurs on them during GET
            if request.method == "GET":
                if request.endpoint == "index":
                    extra_context = { "rows": [], "balance": session.get("balance",0), "deposit": session.get("deposit",0), "withdraw": session.get("withdraw",0), "sum": session.get("sum",0) }
                elif request.endpoint == "sell": # For sell GET page
                    extra_context = {"rows": []}
                elif request.endpoint == "history":
                     extra_context = {"rows": [], "sum":session.get("sum",0), "balance":session.get("balance",0), "deposit":session.get("deposit",0), "withdraw":session.get("withdraw",0)}
                # Add other specific GET contexts if needed for re-rendering on error
            return render_template(template_name, username=username_for_template, **extra_context)
        except Exception:
            # Fallback if template rendering fails or template doesn't exist for the endpoint
            return redirect(url_for("index"))
    return redirect(url_for("index")) # Default fallback


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
        f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote_plus(symbol)}"
        f"?period1={int(start.timestamp())}"
        f"&period2={int(end.timestamp())}"
        f"&interval=1d&events=history&includeAdjustedClose=true"
    )

    # Query API
    try:
        response = request_session.get(url)
        response.raise_for_status()

        data = response.json()
        result = data["chart"]["result"][0]["meta"]["regularMarketPrice"]

        exchange_rate = request_session.get(
            f"https://v6.exchangerate-api.com/v6/{api_key}/pair/USD/INR").json()["conversion_rate"]
        price = exchange_rate * result
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

# Configure CS50 Library to use SQLite database # This line is removed as db is now Firestore


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
    if not db: return apology("currently unable to access database", 503)
    try:
        user_doc_ref = db.collection("users").document(session["user_id"])
        user_snapshot = user_doc_ref.get()

        if not user_snapshot.exists:
            session.clear() # User data missing, clear session and force login
            return apology("User data not found. Please log in again.", 404)
        usrdata = user_snapshot.to_dict()

        # Fetch all required data (from history subcollection)
        history_ref = user_doc_ref.collection("history")
        history_docs_query = history_ref.stream()

        aggregated_portfolio = {}
        for doc in history_docs_query:
            item = doc.to_dict()
            symbol = item["symbol"]
            if symbol not in aggregated_portfolio:
                # Initialize structure for each symbol
                aggregated_portfolio[symbol] = {"shares": 0, "total_cost_basis": 0, "symbol": symbol}
            aggregated_portfolio[symbol]["shares"] += item.get("shares", 0)
            # 'total' in history is price * shares at time of transaction
            # For buys, total is positive cost. For sells, total is negative proceeds.
            # Summing them up gives the net cost basis for currently held shares.
            aggregated_portfolio[symbol]["total_cost_basis"] += item.get("total", 0)


        # Initialize variables
        param = []
        current_grand_total_value = 0.0
        session["balance"] = float(usrdata.get("cash", 0.0))
        session["deposit"] = float(usrdata.get("deposit", 0.0))
        session["withdraw"] = float(usrdata.get("withdraw", 0.0))

        for symbol, data in aggregated_portfolio.items():
            if data["shares"] > 0: # Only process stocks currently owned
                quote = lookup(symbol)
                if quote:
                    current_price = quote["price"]
                    current_value_of_holding = current_price * data["shares"]
                    # Average cost price for the shares currently held
                    avg_cost_price = (data["total_cost_basis"] / data["shares"]) if data["shares"] != 0 else 0

                    param.append({
                        "symbol": symbol,
                        "shares": data["shares"],
                        "price": current_price,
                        "oldprice": avg_cost_price,
                        "total": current_value_of_holding
                    })
                    current_grand_total_value += current_value_of_holding
                else:
                    # Handle case where lookup fails for an owned stock
                    avg_cost_price_fallback = (data["total_cost_basis"] / data["shares"]) if data["shares"] != 0 else "N/A"
                    param.append({
                        "symbol": symbol, "shares": data["shares"], "price": "N/A",
                        "oldprice": avg_cost_price_fallback,
                        "total": "N/A"
                    })

        session["sum"] = current_grand_total_value

        return render_template("index.html", rows=param, balance=session["balance"], username=session["username"],
                               deposit=session["deposit"], withdraw=session["withdraw"], sum=session["sum"])
    except Exception:
        return apology("currently unable to access database", 503)


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    if not db: return apology("currently unable to access database", 503)
    try:
        user_doc_ref = db.collection("users").document(session["user_id"])
        # Order by time, descending to show newest first
        history_query = user_doc_ref.collection("history").order_by("time", direction=firestore.Query.DESCENDING)
        history_docs = history_query.stream()

        rows = []
        for doc in history_docs:
            data = doc.to_dict()
            # Format timestamp for display
            time_val = data.get("time")
            if isinstance(time_val, datetime.datetime):
                # Firestore timestamps are timezone-aware (UTC by default if set by SERVER_TIMESTAMP)
                # Format as needed, e.g., to local time if desired, or just string representation
                data["time_formatted"] = time_val.strftime('%Y-%m-%d %H:%M:%S')
            elif isinstance(time_val, (int, float)): # If stored as epoch
                data["time_formatted"] = datetime.datetime.fromtimestamp(time_val).strftime('%Y-%m-%d %H:%M:%S')
            else: # Fallback for other types or if time is missing
                data["time_formatted"] = str(time_val if time_val else "N/A")
            rows.append(data)

        # Retrieve history and create the view with user-specific data
        # Also fetch current user data for balance display consistency in template
        user_snapshot = user_doc_ref.get()
        usrdata = user_snapshot.to_dict() if user_snapshot.exists else {}

        return render_template("history.html", rows=rows, username=session["username"],
                               sum=session.get("sum", usrdata.get("sum",0.0)), # Use session or fresh from usrdata
                               balance=session.get("balance", usrdata.get("cash",0.0)),
                               deposit=session.get("deposit", usrdata.get("deposit",0.0)),
                               withdraw=session.get("withdraw", usrdata.get("withdraw",0.0)))
    except Exception:
        return apology("currently unable to access database", 503)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if not db: return apology("currently unable to access database", 503)
    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        # Ensure username was submitted
        if not str(username).isalnum():
            return apology("invalid username", 400)
        # Ensure password was submitted
        elif not str(password).isascii():
            return apology("invalid password", 400)
        # Ensure password was confirmed
        elif not str(confirmation).isascii():
            return apology("invalid password confirmation", 400)
        # Ensure password and confirmation are the same
        elif password != confirmation:
            return apology("password and confirmation do not match", 400)
        # Check for username specifications
        elif not (8 <= len(str(username)) <= 16):
            return apology("username must contain 8-16 characters", 400)

        # Check for password specifications
        flag1 = False
        flag2 = False
        flag3 = False
        for i in str(password):
            if i.isalpha():
                flag1 = True
            elif i.isdigit():
                flag2 = True
            else:
                flag3 = True
        if not (flag1 and flag2 and flag3):
            return apology("password must contain atleast one alphabet, number and special character", 400)
        elif not (8 <= len(str(password)) <= 16):
            return apology("password must contain 8-16 characters", 400)

        try:
            users_ref = db.collection("users")
            # Ensure username does not already exist
            query = users_ref.where(filter=firestore.FieldFilter("username", "==", username)).limit(1).stream()
            if len(list(query)) > 0:
                return apology("username already exists", 400)

            # Insert new user into database
            new_user_data = {
                "username": username,
                "hash": generate_password_hash(password),
                "cash": 0.0,
                "deposit": 0.0,
                "withdraw": 0.0,
                "created_at": firestore.SERVER_TIMESTAMP
            }
            update_time, doc_ref = users_ref.add(new_user_data)

            # Remember which user has logged in
            session["user_id"] = doc_ref.id
            session["username"] = username
            flash("Welcome " + username + "!")

            # Redirect user to home page
            return redirect("/")
        except Exception:
            return apology("currently unable to access database", 503)

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("register.html", username=session.get("username", ""))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""
    if not db: return apology("currently unable to access database", 503)
    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        # Ensure username was submitted
        if not str(username).isalnum():
            return apology("invalid username", 403)
        # Ensure password was submitted
        elif not str(password).isascii():
            return apology("invalid password", 403)

        try:
            # Query database for username
            users_ref = db.collection("users")
            query = users_ref.where(filter=firestore.FieldFilter("username", "==", username)).limit(1).stream()
            user_docs = list(query)

            # Ensure username exists and password is correct
            if len(user_docs) != 1 or not check_password_hash(
                user_docs[0].to_dict().get("hash",""), password
            ):
                return apology("invalid username and/or password", 403)

            user_data = user_docs[0].to_dict()
            user_id = user_docs[0].id

            # Remember which user has logged in
            session["user_id"] = user_id
            session["username"] = user_data["username"]
            # Populate session with financial data on login
            session["balance"] = float(user_data.get("cash", 0.0))
            session["deposit"] = float(user_data.get("deposit", 0.0))
            session["withdraw"] = float(user_data.get("withdraw", 0.0))
            # session["sum"] will be calculated by index route

            flash("Welcome " + user_data["username"] + "!")
            # Redirect user to home page
            return redirect("/")
        except Exception:
            return apology("currently unable to access database", 503)

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html", username=session.get("username", ""))


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
        symbol_input = request.form.get("symbol")
        # Check if symbol is valid
        if str(symbol_input).isalnum():
            quote = lookup(symbol_input)

            # Get charts for the symbol
            if quote:
                url1 = f"https://api.wsj.net/api/kaavio/charts/big.chart?nosettings=1&symb={quote['symbol']}&uf=0&type=2&size=2&style=320&freq=1&time=7&compidx=&ma=0&maval=9&lf=1&lf2=0&lf3=0&height=335&width=579&mocktick=1"
                url2 = f"https://api.wsj.net/api/kaavio/charts/big.chart?nosettings=1&symb={quote['symbol']}&uf=0&type=2&size=2&style=320&freq=2&time=12&compidx=&ma=0&maval=9&lf=1&lf2=0&lf3=0&height=335&width=579&mocktick=1"
                return render_template("search.html", quote=quote, username=session["username"], url1=url1, url2=url2)
            else:
                return apology("invalid symbol or data not found", 400)
        else:
            return apology("invalid symbol", 400)

    else:
        return render_template("search.html", quote="", username=session["username"])


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if not db: return apology("currently unable to access database", 503)
    if request.method == "POST":
        symbol_input = request.form.get("symbol")
        shares_input = request.form.get("shares")

        # Check for invalid entries
        if str(symbol_input).isalnum():
            quote = lookup(symbol_input)
        else:
            return apology("invalid symbol", 400)
        try:
            shares = int(shares_input) # Shares must be whole numbers
        except (ValueError, TypeError):
            return apology("invalid entry for shares", 400)

        if not quote:
            return apology("invalid symbol or stock data not found", 400)
        elif shares <= 0: # Check if shares is positive
            return apology("shares must be a positive number", 400)

        cost = quote["price"] * shares

        try:
            user_ref = db.collection("users").document(session["user_id"])

            # Check balance (Optimistic check before transaction)
            current_user_snapshot_for_balance_check = user_ref.get()
            if not current_user_snapshot_for_balance_check.exists:
                return apology("User data error", 500)
            current_balance_from_db = float(current_user_snapshot_for_balance_check.to_dict().get("cash", 0.0))
            if cost > current_balance_from_db:
                return apology("insufficient balance", 400)

            @firestore.transactional
            def buy_transaction(transaction, user_doc_ref, purchase_cost, quote_data, num_shares):
                snapshot = user_doc_ref.get(transaction=transaction)
                if not snapshot.exists: raise Exception("User not found during transaction")

                user_data = snapshot.to_dict()
                if user_data is None:
                    raise Exception("User data is unexpectedly None in transaction")
                current_cash = float(user_data.get("cash", 0.0))
                if current_cash < purchase_cost:

                    raise ValueError("Insufficient balance")

                new_cash = current_cash - purchase_cost
                transaction.update(user_doc_ref, {"cash": new_cash})

                history_doc_ref = user_doc_ref.collection("history").document() # Auto-ID
                transaction_data = {
                    "symbol": quote_data["symbol"], "price": quote_data["price"],
                    "shares": num_shares, "time": firestore.SERVER_TIMESTAMP,
                    "total": purchase_cost, "type": "buy"
                }
                transaction.set(history_doc_ref, transaction_data)
                return new_cash

            # Execute the transaction
            new_balance_after_buy = buy_transaction(db.transaction(), user_ref, cost, quote, shares)

            # Update session
            session["balance"] = new_balance_after_buy

            flash("Bought Stocks Successfully")
            row_display = {"symbol": quote["symbol"], "price": quote["price"], "shares": shares}
            # Pass the balance *before* transaction for display, and new balance for currbalance
            return render_template("transaction.html", row=row_display, balance=current_balance_from_db,
                                   currbalance=session["balance"], username=session["username"])

        except ValueError as ve: # Specifically for "Insufficient balance" from transaction
            if str(ve) == "Insufficient balance":
                return apology("insufficient balance", 400)
            return apology("An error occurred during purchase.", 400) # Other ValueErrors
        except google_exceptions.GoogleAPICallError as e:
            app.logger.error(f"Firebase API error in buy route: {e}")
            return apology("currently unable to access database", 503)
        except Exception as e:
            app.logger.error(f"Unexpected error in buy route: {e}")
            return apology("An unexpected error occurred during purchase.", 500)
    else:
        return render_template("buy.html", username=session["username"])


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if not db: return apology("currently unable to access database", 503)
    if request.method == "POST":
        symbol_to_sell = request.form.get("symbol", "").upper()
        shares_to_sell_input = request.form.get("shares")

        # Check for invalid entries
        if not symbol_to_sell:
            return apology("missing symbol", 400)
        if str(symbol_to_sell).isalnum():
            quote = lookup(symbol_to_sell)
        else:
            return apology("invalid symbol", 400)
        try:
            shares_to_sell = int(shares_to_sell_input) # Shares must be whole numbers
        except (ValueError, TypeError):
            return apology("invalid entry for shares", 400)

        if not quote:
            return apology("invalid symbol or stock data not found", 400)
        if shares_to_sell <= 0:
            return apology("shares must be a positive number", 400)

        proceeds = quote["price"] * shares_to_sell

        try:
            user_ref = db.collection("users").document(session["user_id"])

            @firestore.transactional
            def sell_transaction(transaction, user_doc_ref, symbol, num_shares_to_sell, sale_proceeds, current_quote_price):
                # Check current holdings within the transaction
                history_snapshot_query = user_doc_ref.collection("history").where(filter=firestore.FieldFilter("symbol", "==", symbol))
                history_docs_for_symbol = history_snapshot_query.stream(transaction=transaction)

                current_shares_owned = sum(doc.to_dict().get("shares", 0) for doc in history_docs_for_symbol)

                if current_shares_owned < num_shares_to_sell:
                    raise ValueError("Insufficient shares")

                user_snapshot = user_doc_ref.get(transaction=transaction)
                if not user_snapshot.exists: raise Exception("User not found during transaction")

                user_data = user_snapshot.to_dict()
                if user_data is None:
                    raise Exception("User data is unexpectedly None in transaction")
                new_cash = float(user_data.get("cash", 0.0)) + sale_proceeds
                transaction.update(user_doc_ref, {"cash": new_cash})

                history_doc_ref = user_doc_ref.collection("history").document() # Auto-ID
                transaction_data = {
                    "symbol": symbol, "price": current_quote_price,
                    "shares": -num_shares_to_sell, # Negative for sell
                    "time": firestore.SERVER_TIMESTAMP,
                    "total": -sale_proceeds, # Negative total for sell
                    "type": "sell"
                }
                transaction.set(history_doc_ref, transaction_data)
                return new_cash

            # Get balance before transaction for display
            current_user_snapshot_for_balance_check = user_ref.get()
            if not current_user_snapshot_for_balance_check.exists:
                return apology("User data error", 500)
            balance_before_sell = float(current_user_snapshot_for_balance_check.to_dict().get("cash", 0.0))

            # Execute transaction
            new_balance_after_sell = sell_transaction(db.transaction(), user_ref, symbol_to_sell, shares_to_sell, proceeds, quote["price"])

            # Update session
            session["balance"] = new_balance_after_sell

            flash("Sold Stocks Successfully")
            row_display = {"symbol": symbol_to_sell, "price": quote["price"], "shares": shares_to_sell}
            return render_template("transaction.html", row=row_display, balance=balance_before_sell,
                                   currbalance=session["balance"], username=session["username"])

        except ValueError as ve: # Specifically for "Insufficient shares"
            if str(ve) == "Insufficient shares":
                return apology("insufficient shares", 400)
            return apology("An error occurred during sale.", 400) # Other ValueErrors
        except google_exceptions.GoogleAPICallError as e:
            app.logger.error(f"Firebase API error in sell route: {e}")
            return apology("currently unable to access database", 503)
        except Exception as e:
            app.logger.error(f"Unexpected error in sell route: {e}")
            return apology("An unexpected error occurred during sale.", 500)
    else: # GET request
        try:
            user_doc_ref = db.collection("users").document(session["user_id"])
            history_docs = user_doc_ref.collection("history").stream()

            owned_symbols_agg = {}
            for doc in history_docs:
                item = doc.to_dict()
                symbol = item["symbol"]
                owned_symbols_agg[symbol] = owned_symbols_agg.get(symbol, 0) + item.get("shares",0)

            # Provide symbols that user actually owns (shares > 0)
            symbols_for_template = [{"symbol": sym} for sym, count in owned_symbols_agg.items() if count > 0]
            return render_template("sell.html", rows=symbols_for_template, username=session["username"])
        except Exception:
            return apology("currently unable to access database", 503)


@app.route("/deposit", methods=["GET", "POST"])
@login_required
def deposit():
    """Add cash to account"""
    if not db: return apology("currently unable to access database", 503)
    if request.method == "POST":
        cash_input = request.form.get("amount")

        # Check for invalid entries
        try:
            cash_to_deposit = float(cash_input)
        except (ValueError, TypeError):
            return apology("invalid amount", 400)
        if cash_to_deposit <= 0:
            return apology("invalid amount", 400)

        try:
            user_ref = db.collection("users").document(session["user_id"])

            # Get balance before transaction for display
            current_user_snapshot_for_balance_check = user_ref.get()
            if not current_user_snapshot_for_balance_check.exists:
                return apology("User data error", 500)
            balance_before_deposit = float(current_user_snapshot_for_balance_check.to_dict().get("cash", 0.0))
            deposit_before_deposit = float(current_user_snapshot_for_balance_check.to_dict().get("deposit", 0.0))


            @firestore.transactional
            def deposit_cash_tx(transaction, user_doc_ref, amount_to_deposit):
                snapshot = user_doc_ref.get(transaction=transaction)
                if not snapshot.exists: 
                    raise Exception("User not found")
                user_data = snapshot.to_dict()
                if user_data is None:
                    raise Exception("User data is unexpectedly None in transaction")
                new_cash = float(user_data.get("cash", 0.0)) + amount_to_deposit
                new_deposit_total = float(user_data.get("deposit", 0.0)) + amount_to_deposit
                transaction.update(user_doc_ref, {"cash": new_cash, "deposit": new_deposit_total})
                return new_cash, new_deposit_total

            new_balance, new_total_deposited = deposit_cash_tx(db.transaction(), user_ref, cash_to_deposit)

            # Update session
            session["balance"] = new_balance
            session["deposit"] = new_total_deposited

            flash("Cash Deposited Successfully")
            row_display = {"symbol": "Cash Deposited", "price": cash_to_deposit, "shares": 0}
            return render_template("transaction.html", row=row_display, balance=balance_before_deposit,
                                   currbalance=session["balance"], username=session["username"])
        except Exception:
            return apology("currently unable to access database", 503)
    else:
        return render_template("deposit.html", username=session["username"])


@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():
    """Add cash to account""" # Original comment, though "Withdraw cash" might be more apt
    if not db: return apology("currently unable to access database", 503)
    if request.method == "POST":
        cash_input = request.form.get("amount")
        # Check for invalid entries
        try:
            cash_to_withdraw = float(cash_input)
        except (ValueError, TypeError):
            return apology("invalid amount", 400)
        if cash_to_withdraw <= 0:
            return apology("invalid amount", 400)

        try:
            user_ref = db.collection("users").document(session["user_id"])

            # Get balance before transaction for display and pre-check
            current_user_snapshot_for_balance_check = user_ref.get()
            if not current_user_snapshot_for_balance_check.exists:
                return apology("User data error", 500)
            balance_before_withdraw = float(current_user_snapshot_for_balance_check.to_dict().get("cash", 0.0))

            if cash_to_withdraw > balance_before_withdraw:
                return apology("insufficient balance", 400)

            @firestore.transactional
            def withdraw_cash_tx(transaction, user_doc_ref, amount_to_withdraw):
                snapshot = user_doc_ref.get(transaction=transaction)
                if not snapshot.exists: 
                    raise Exception("User not found")
                
                user_data = snapshot.to_dict()
                if user_data is None:
                    raise Exception("User data is unexpectedly None in transaction")
                current_cash = float(user_data.get("cash", 0.0))
                if current_cash < amount_to_withdraw: # Double check within transaction
                    raise ValueError("Insufficient balance for withdrawal")

                new_cash = current_cash - amount_to_withdraw
                new_withdraw_total = float(user_data.get("withdraw", 0.0)) + amount_to_withdraw
                transaction.update(user_doc_ref, {"cash": new_cash, "withdraw": new_withdraw_total})
                return new_cash, new_withdraw_total

            new_balance, new_total_withdrawn = withdraw_cash_tx(db.transaction(), user_ref, cash_to_withdraw)

            # Update session
            session["balance"] = new_balance
            session["withdraw"] = new_total_withdrawn

            flash("Cash Withdrawn Successfully")
            row_display = {"symbol": "Cash Withdrawn", "price": cash_to_withdraw, "shares": 0}
            return render_template("transaction.html", row=row_display, balance=balance_before_withdraw,
                                   currbalance=session["balance"], username=session["username"])
        except ValueError as ve:
            if str(ve) == "Insufficient balance for withdrawal":
                return apology("insufficient balance", 400)
            return apology("An error occurred during withdrawal.", 400)
        except Exception:
            return apology("currently unable to access database", 503)
    else:
        return render_template("withdraw.html", username=session["username"])


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """User profile with options to change password or delete account"""
    if not db: return apology("currently unable to access database", 503)
    if request.method == "POST":
        # Get the action (change password or delete account)
        action = request.form.get("action")
        current_password = request.form.get("current_password")

        try:
            user_ref = db.collection("users").document(session["user_id"])
            user_snapshot = user_ref.get()

            # Query database for the current user (already done by getting user_snapshot)
            if not user_snapshot.exists:
                return apology("User not found", 404) # Should not happen if login_required works
            user_data = user_snapshot.to_dict()

            # Ensure the current password is correct
            if not check_password_hash(user_data.get("hash", ""), current_password):
                return apology("invalid current password", 400)

            if action == "change_password":
                # Ensure new password and confirmation are provided
                new_password = request.form.get("new_password")
                confirmation = request.form.get("confirmation")

                if not new_password or not confirmation:
                    return apology("missing new password or confirmation", 400)
                # Ensure new password and confirmation match
                if new_password != confirmation:
                    return apology("new password and confirmation do not match", 400)

                # Check for password specifications
                flag1 = any(c.isalpha() for c in new_password)
                flag2 = any(c.isdigit() for c in new_password)
                flag3 = any(not c.isalnum() for c in new_password)

                if not (flag1 and flag2 and flag3):
                    return apology("password must contain at least one alphabet, number, and special character", 400)
                elif not (8 <= len(new_password) <= 16) :
                    return apology("password must contain 8-16 characters", 400)

                # Update the password in the database
                user_ref.update({"hash": generate_password_hash(new_password)})
                flash("Password Changed Successfully")
                return redirect("/profile")

            elif action == "delete_account":
                # Delete the user account from the database
                # First, delete all documents in the 'history' subcollection
                history_coll_ref = user_ref.collection('history')
                docs_to_delete_stream = history_coll_ref.limit(500).stream() # Process in batches
                
                while True:
                    batch = db.batch()
                    doc_count_in_batch = 0
                    for doc_del in docs_to_delete_stream:
                        batch.delete(doc_del.reference)
                        doc_count_in_batch +=1
                    
                    if doc_count_in_batch == 0: # No more documents to delete
                        break
                    
                    batch.commit()
                    
                    if doc_count_in_batch < 500: # Last batch was processed
                        break
                    # Fetch next batch
                    docs_to_delete_stream = history_coll_ref.limit(500).stream()

                # Then, delete the user document itself
                user_ref.delete()
                session.clear()
                flash("Account Deleted Successfully")
                return redirect("/register")
        except Exception:
            return apology("currently unable to access database", 503)

    # Render the profile page
    return render_template("profile.html", username=session["username"])
