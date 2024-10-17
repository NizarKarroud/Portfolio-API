from flask import Flask, jsonify, render_template, request, redirect, url_for
import jwt
import datetime
from flask_mysqldb import MySQL
from functools import wraps
import os , json
from dotenv import load_dotenv
import pandas as pd

app = Flask(__name__)

load_dotenv()

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB')

mysql = MySQL(app)

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.args.get('token')
        
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            current_user = data['user_id']
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Token has expired!'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Token is invalid!'}), 401
        
        return f(token , current_user, *args, **kwargs)
    
    return decorated

def validate_login(id: int, password: str):

    cur = mysql.connection.cursor()
    try:
        cur.execute("SELECT password FROM client WHERE idclient=%s", (id,))
        result = cur.fetchone()
        cur.close()
        if result and password == result[0]:
            return True
        else:
            return False
    except Exception:
        return False

def fetch_stocks():
    cur = mysql.connection.cursor()
    try:
        cur.execute("SELECT * FROM action")
        result = cur.fetchall()
        cur.close()
        return result
    except Exception:
        return None

def fetch_profile(id):
    cur = mysql.connection.cursor()
    try:
        cur.execute(f"SELECT nom_client , solde FROM client WHERE idclient={id}")
        name, balance = cur.fetchone()
        cur.execute(f"SELECT COUNT(*) FROM actions_client WHERE idclient={id};")
        owned_number = cur.fetchone()[0]
        cur.close()
        return {
            "name": name,
            "id": id,
            "owned_stocks": owned_number,
            "balance": balance
        }
    except Exception:
        return None

def buy(user_id , stock_id , price , number,entity):
    cur = mysql.connection.cursor()
    try:
        cur.execute(f"SELECT nombre FROM action WHERE idaction={stock_id};")
        available_number = cur.fetchone()
        print("available number : " ,available_number[0])
        if available_number[0]:
            cur.execute(f"SELECT solde FROM client WHERE idclient={user_id};")
            user_balance = cur.fetchone()
            print("user balance : " , user_balance[0])
            if user_balance[0] >= price:
                new_balance = user_balance[0] - price
                cur.execute(f"UPDATE client SET solde={new_balance} WHERE idclient={user_id};")
                print("new balance :" , new_balance)

                remaining_stocks = available_number[0] - number
                print("remaining stocks : " , remaining_stocks)
                if remaining_stocks > 0:
                    cur.execute(f"UPDATE action SET nombre={remaining_stocks} WHERE idaction={stock_id};")
                else:
                    cur.execute(f"UPDATE action SET nombre=0 WHERE idaction={stock_id};")
                cur.execute(f"SELECT nombre FROM actions_client WHERE idclient={user_id} AND idaction={stock_id};")
                owned_stocks = cur.fetchone()
                print("owned stocks :" , owned_stocks)
                if owned_stocks:
                    new_owned_number = owned_stocks[0] + number
                    cur.execute(f"UPDATE actions_client SET nombre={new_owned_number} WHERE idclient={user_id} AND idaction={stock_id};")
                else:
                    cur.execute(f"INSERT INTO actions_client (idclient, idaction, nombre) VALUES ({user_id}, {stock_id}, {number});")
                mysql.connection.commit()
                return f"Buy request successful: Purchased {number} of stock {stock_id} from {entity}."
            else:
                return "Buy request denied: Insufficient balance."
        else:
            return "Buy request denied: Not enough stocks available"

    except Exception as err:
        mysql.connection.rollback()
        return f"Error processing buy request"

def fetch_owned(id):
    df = pd.read_sql_query(f"SELECT idaction , nombre FROM actions_client WHERE idclient={id};" , mysql.connection)
    idactions = df['idaction'].tolist()
    idactions_str = ','.join([str(action) for action in idactions])
    prices_df =  pd.read_sql_query(f"SELECT idaction, societe,prix FROM action WHERE idaction IN ({idactions_str});" , mysql.connection)
    df = df.merge(prices_df, on='idaction', how='left')
    owned_stocks = df.to_json(orient="records")
    return owned_stocks

def sell(user_id , stock_id , price , number,entity):
    cur = mysql.connection.cursor()
    price = int(price)
    sold_number = int(number)
    single_price = price // sold_number
    try:
        cur.execute(f"SELECT nombre FROM actions_client WHERE idaction={stock_id};")
        owned_number = cur.fetchone()
        if sold_number < owned_number[0]:
            new_owned = owned_number[0] - sold_number
            cur.execute(
                f"UPDATE actions_client SET nombre={new_owned} WHERE idclient={user_id} AND idaction={stock_id};")
        else:
            cur.execute(f"DELETE FROM actions_client WHERE idaction={stock_id} AND idaction={stock_id};")
    
        cur.execute(f"SELECT idaction , nombre FROM action WHERE idaction={stock_id};")
        available_stock = cur.fetchone()
        if available_stock[0]:
            new_action_number = int(available_stock[1]) + sold_number
            cur.execute(
                f"UPDATE action SET nombre={new_action_number} WHERE idaction={available_stock[0]};")
        else:
            cur.execute(
                f"INSERT INTO action (idaction, nombre, prix,societe) VALUES ({stock_id},{sold_number},{single_price} , {entity});")
        cur.execute(f"SELECT solde FROM client WHERE idclient={user_id}")
        user_solde = cur.fetchone()
        updated_solde = int(user_solde[0]) + price
        cur.execute(f"UPDATE client SET solde={updated_solde} WHERE idclient={user_id} ;")
        mysql.connection.commit()
        return f"Sale request successful"
    except Exception as err:
        mysql.connection.rollback()
        return "Error processing sale request."

@app.route('/')
def root():
    return redirect(url_for('login_page'))

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        id = request.form['id']
        password = request.form['password']
        user_validity = validate_login(id, password)
        
        if user_validity:
            token = jwt.encode(
                {"user_id": id, 'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)},
                app.config['SECRET_KEY']
            )
            return redirect(url_for('dashboard', token=token))
            
        else:
            error_message = "Invalid credentials. Please try again."
            return render_template('login.html', error=error_message)
    
    return render_template('login.html')

@app.route('/dashboard')
@token_required
def dashboard(token ,current_user):
    return render_template("welcome.html" , token = token )

@app.route('/stocks')
@token_required
def display_stocks(token ,current_user):
    stocks = fetch_stocks()
    return render_template('stocks_page.html', token = token , stocks=stocks )

@app.route('/buy', methods=['POST'])
@token_required
def buy_stock(token, current_user):
    stock_id = request.form.get('stock_id')
    entity = request.form.get('entity')
    number = request.form.get('number')
    price = request.form.get('price')
    return render_template("buy_stock.html" , token=token ,stock_id =stock_id , entity=entity , number = number , price=price )

@app.route('/confirm_purchase', methods=['POST'])
@token_required
def confirm_purchase(token , current_user):
    stock_id = request.form.get('stock_id')
    entity = request.form.get('entity')
    number = int(request.form.get('number'))
    price = int(number) * int( request.form.get('price'))
    result = buy(current_user ,stock_id , price , number ,entity)
    return  render_template("message.html" , message=result , token=token)

@app.route('/owned_stocks')
@token_required
def owned_stocks(token ,current_user):
    stocks = fetch_owned(current_user)
    stocks = json.loads(stocks)
    print(stocks)
    return render_template("owned_stocks.html" , token =token ,stocks=stocks)

@app.route('/sell', methods=['POST'])
@token_required
def sell_stock(token, current_user):
    stock_id = request.form.get('stock_id')
    entity = request.form.get('entity')
    number = request.form.get('number')
    price = request.form.get('price')
    return render_template("sell_stock.html" , token=token ,stock_id =stock_id , entity=entity , number = number , price=price )

@app.route('/confirm_sale', methods=['POST'])
@token_required
def confirm_sale(token , current_user):
    stock_id = request.form.get('stock_id')
    entity = request.form.get('entity')
    number = int(request.form.get('number'))
    price = int(number) * int( request.form.get('price'))
    result = sell(current_user ,stock_id , price , number ,entity)
    return  render_template("message.html" , message=result , token=token)

@app.route('/profile')
@token_required
def profile(token ,current_user):
    profile_data = fetch_profile(current_user)
    return render_template("profile.html", profile=profile_data)

if __name__ == '__main__':
    app.run('0.0.0.0', 16000)
