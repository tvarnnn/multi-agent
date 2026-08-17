from flask import Flask, request, jsonify
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)

# Dummy user data for demonstration purposes
users = {
    'user1': generate_password_hash('password123'),
    'user2': generate_password_hash('securepass')
}

def login(username, password):
    # Check if the user exists
    if username in users:
        # Verify the password
        if check_password_hash(users[username], password):
            return True
        else:
            return False, 'Invalid password'
    else:
        return False, 'User not found'

@app.route('/login', methods=['POST'])
def handle_login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400
    
    success, message = login(username, password)
    if success:
        return jsonify({'message': 'Login successful'}), 200
    else:
        return jsonify({'error': message}), 401

if __name__ == '__main__':
    app.run(debug=True)