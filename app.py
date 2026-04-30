from flask import session, Flask, render_template, request, redirect, jsonify, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, date

app = Flask(__name__)
app.secret_key = "secret123"  # Replace with a real secret key

# Database config
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

project_members = db.Table(
    'project_members',
    db.Column('project_id', db.Integer, db.ForeignKey('project.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)

# ---------------- MODELS ---------------- #

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    role = db.Column(db.String(20))  # admin / member
    tasks = db.relationship('Task', backref='assignee', lazy=True, foreign_keys='Task.assigned_to')
    projects = db.relationship('Project', secondary=project_members, back_populates='members')

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    creator = db.relationship('User', foreign_keys=[created_by])
    members = db.relationship('User', secondary=project_members, back_populates='projects')
    tasks = db.relationship('Task', backref='project', lazy=True)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    status = db.Column(db.String(50))
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'))
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'))
    deadline = db.Column(db.String(50))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

def api_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        role = request.form.get('role')

        if not name or not email or not password or role not in ['admin', 'member']:
            error = 'All fields are required and role must be valid.'
        elif User.query.filter_by(email=email).first():
            error = 'Email already registered. Try another email.'
        else:
            user = User(
                name=name,
                email=email,
                password=generate_password_hash(password),
                role=role
            )
            db.session.add(user)
            db.session.commit()
            return redirect(url_for('login'))

    return render_template('register.html', error=error)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(
            email=request.form['email']
        ).first()

        if user and check_password_hash(user.password, request.form['password']):
            session['user_id'] = user.id
            session['role'] = user.role
            return redirect('/dashboard')
        else:
            return "Invalid Credentials"

    return render_template('login.html')

@app.route('/')
def index():
    # Always send the user to login first, even if a previous session cookie exists.
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session.get('user_id')
    role = session.get('role')

    if role == 'admin':
        projects = Project.query.all()
        tasks = Task.query.all()
    else:
        projects = Project.query.filter(Project.members.any(id=user_id)).all()
        tasks = Task.query.filter_by(assigned_to=user_id).all()

    total = len(tasks)
    completed = len([t for t in tasks if t.status == "Completed"])
    pending = len([t for t in tasks if t.status == "Pending"])

    today = date.today()
    overdue = len([
        t for t in tasks
        if t.deadline and datetime.strptime(t.deadline, '%Y-%m-%d').date() < today and t.status != "Completed"
    ])

    return render_template(
        'dashboard.html',
        projects=projects,
        tasks=tasks,
        total=total,
        completed=completed,
        pending=pending,
        overdue=overdue
    )
@app.route('/create_project', methods=['GET', 'POST'])
@login_required
def create_project():
    if session.get('role') != 'admin':
        return "Access Denied", 403

    members = User.query.filter_by(role='member').all()
    error = None
    selected_members = []

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        selected_members = request.form.getlist('members')

        if not name:
            error = 'Project name is required.'
        elif not selected_members:
            error = 'Select at least one team member for the project.'
        else:
            users = User.query.filter(User.id.in_(selected_members), User.role == 'member').all()
            if len(users) != len(selected_members):
                error = 'One or more selected members are invalid.'
            else:
                project = Project(name=name, created_by=session['user_id'])
                project.members = users
                db.session.add(project)
                db.session.commit()
                return redirect(url_for('dashboard'))

    return render_template('create_project.html', error=error, members=members, selected_members=selected_members)

@app.route('/create_task', methods=['GET', 'POST'])
@login_required
def create_task():
    if session.get('role') != 'admin':
        return "Access Denied", 403

    users = User.query.filter_by(role='member').all()
    projects = Project.query.all()
    error = None
    selected_assigned_to = None
    selected_project_id = None

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        assigned_to = request.form.get('assigned_to')
        project_id = request.form.get('project_id')
        deadline_str = request.form.get('deadline')
        selected_assigned_to = assigned_to
        selected_project_id = project_id

        if not title or not assigned_to or not project_id:
            error = 'Title, assignee, and project are required.'
        else:
            assignee = User.query.get(int(assigned_to)) if assigned_to.isdigit() else None
            project = Project.query.get(int(project_id)) if project_id.isdigit() else None
            if not assignee or not project:
                error = 'Invalid assignee or project.'
            elif assignee.role != 'member':
                error = 'Tasks must be assigned to team members.'
            elif assignee not in project.members:
                error = 'Assignee must be a member of the selected project.'
            else:
                if deadline_str:
                    try:
                        deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
                        if deadline < date.today():
                            error = 'Deadline must be in the future.'
                    except ValueError:
                        error = 'Invalid deadline format.'

        if not error:
            task = Task(
                title=title,
                status="Pending",
                assigned_to=int(assigned_to),
                project_id=int(project_id),
                deadline=deadline_str
            )
            db.session.add(task)
            db.session.commit()
            return redirect(url_for('dashboard'))

    return render_template(
        'create_task.html',
        users=users,
        projects=projects,
        error=error,
        selected_assigned_to=selected_assigned_to,
        selected_project_id=selected_project_id
    )

@app.route('/update_task/<int:id>/<status>')
@login_required
def update_task(id, status):
    task = Task.query.get(id)
    if not task:
        return "Task not found", 404

    allowed_statuses = ['Pending', 'In Progress', 'Completed']
    if status not in allowed_statuses:
        return 'Invalid status', 400

    if session.get('role') != 'admin' and task.assigned_to != session.get('user_id'):
        return 'Access denied', 403

    task.status = status
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/api/users', methods=['GET'])
@api_login_required
def api_users():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Access denied'}), 403

    users = User.query.all()
    data = [{'id': u.id, 'name': u.name, 'email': u.email, 'role': u.role} for u in users]
    return jsonify(data)

@app.route('/api/projects', methods=['GET', 'POST'])
@api_login_required
def api_projects():
    if request.method == 'POST':
        if session.get('role') != 'admin':
            return jsonify({'error': 'Access denied'}), 403

        data = request.get_json()
        project = Project(name=data['name'], created_by=session['user_id'])
        db.session.add(project)
        db.session.commit()
        return jsonify({'message': 'Project created', 'id': project.id}), 201

    projects = Project.query.all()
    data = [{'id': p.id, 'name': p.name, 'created_by': p.creator.name if p.creator else None} for p in projects]
    return jsonify(data)

@app.route('/api/tasks', methods=['GET', 'POST'])
@api_login_required
def api_tasks():
    if request.method == 'POST':
        if session.get('role') != 'admin':
            return jsonify({'error': 'Access denied'}), 403

        data = request.get_json()
        task = Task(
            title=data['title'],
            status='Pending',
            assigned_to=data['assigned_to'],
            project_id=data['project_id'],
            deadline=data.get('deadline')
        )
        db.session.add(task)
        db.session.commit()
        return jsonify({'message': 'Task created', 'id': task.id}), 201

    tasks = Task.query.all()
    data = [{
        'id': t.id,
        'title': t.title,
        'status': t.status,
        'assigned_to': t.assignee.name if t.assignee else None,
        'project': t.project.name if t.project else None,
        'deadline': t.deadline
    } for t in tasks]
    return jsonify(data)

@app.route('/api/tasks/<int:task_id>', methods=['PATCH'])
@api_login_required
def api_task_update(task_id):
    task = Task.query.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404

    if session.get('role') != 'admin' and task.assigned_to != session.get('user_id'):
        return jsonify({'error': 'Access denied'}), 403

    data = request.get_json()
    if 'status' in data and data['status'] in ['Pending', 'In Progress', 'Completed']:
        task.status = data['status']
        db.session.commit()
        return jsonify({'message': 'Task updated'}), 200

    return jsonify({'error': 'Invalid data'}), 400

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)