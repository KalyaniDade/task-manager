from flask import session, Flask, render_template, request, redirect, jsonify, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, date

app = Flask(__name__)
app.secret_key = "secret123"  # Replace with a real secret key

# Database config
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ---------------- MODELS ---------------- #

class ProjectMember(db.Model):
    __tablename__ = 'project_member'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    project = db.relationship('Project', back_populates='memberships')
    user = db.relationship('User', back_populates='project_memberships')

    __table_args__ = (
        db.UniqueConstraint('project_id', 'user_id', name='uq_project_user'),
    )

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)

    tasks = db.relationship('Task', back_populates='assignee', lazy=True, foreign_keys='Task.assigned_to')
    project_memberships = db.relationship('ProjectMember', back_populates='user', cascade='all, delete-orphan', lazy=True)
    projects = db.relationship('Project', secondary='project_member', back_populates='members')

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    creator = db.relationship('User', foreign_keys=[created_by])
    memberships = db.relationship('ProjectMember', back_populates='project', cascade='all, delete-orphan', lazy=True)
    members = db.relationship('User', secondary='project_member', back_populates='projects')
    tasks = db.relationship('Task', back_populates='project', lazy=True)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), nullable=False, default='To Do')
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    due_date = db.Column(db.Date, nullable=True)

    assignee = db.relationship('User', back_populates='tasks', foreign_keys=[assigned_to])
    project = db.relationship('Project', back_populates='tasks')

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


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    user_id = session.get('user_id')
    return User.query.get(user_id) if user_id else None

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
    if request.method == 'GET':
        session.clear()
        return render_template('login.html')

    user = User.query.filter_by(
        email=request.form['email']
    ).first()

    if user and check_password_hash(user.password, request.form['password']):
        session['user_id'] = user.id
        session['role'] = user.role
        return redirect('/dashboard')
    else:
        return "Invalid Credentials"

@app.route('/')
def index():
    session.clear()
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

    today = date.today()
    overdue_tasks = [
        t for t in tasks
        if t.due_date and t.due_date < today and t.status != 'Completed'
    ]

    stats = {
        'total': len(tasks),
        'to_do': len([t for t in tasks if t.status == 'To Do']),
        'in_progress': len([t for t in tasks if t.status == 'In Progress']),
        'completed': len([t for t in tasks if t.status == 'Completed']),
        'overdue': len(overdue_tasks)
    }

    return render_template(
        'dashboard.html',
        projects=projects,
        tasks=tasks,
        stats=stats,
        overdue_tasks=overdue_tasks,
        role=role,
        today=today
    )

@app.route('/create_project', methods=['GET', 'POST'])
@login_required
def create_project():
    if session.get('role') != 'admin':
        return "Access Denied", 403

    error = None
    description = ''

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()

        if not name:
            error = 'Project name is required.'
        else:
            project = Project(name=name, description=description, created_by=session['user_id'])
            db.session.add(project)
            db.session.commit()
            return redirect(url_for('dashboard'))

    return render_template('create_project.html', error=error, description=description)

@app.route('/edit_project/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_project(id):
    if session.get('role') != 'admin':
        return "Access Denied", 403

    project = Project.query.get(id)
    if not project:
        return "Project not found", 404

    error = None

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()

        if not name:
            error = 'Project name is required.'
        else:
            project.name = name
            project.description = description
            db.session.commit()
            return redirect(url_for('dashboard'))

    return render_template(
        'edit_project.html',
        project=project,
        error=error
    )

@app.route('/projects/<int:project_id>/members', methods=['GET'])
@login_required
def project_members_page(project_id):
    if session.get('role') != 'admin':
        return "Access Denied", 403

    project = Project.query.get(project_id)
    if not project:
        return "Project not found", 404

    members = project.members
    member_ids = [member.id for member in members]
    available_users = User.query.filter(User.role == 'member', ~User.id.in_(member_ids)).all()
    return render_template('manage_members.html', project=project, members=members, available_users=available_users)

@app.route('/projects/<int:project_id>/add-member', methods=['POST'])
@login_required
def add_project_member(project_id):
    if session.get('role') != 'admin':
        return "Access Denied", 403

    project = Project.query.get(project_id)
    if not project:
        return "Project not found", 404

    user_id = request.form.get('user_id')
    user = User.query.filter_by(id=user_id, role='member').first() if user_id else None
    if not user:
        return redirect(url_for('project_members_page', project_id=project_id))

    if user not in project.members:
        project.members.append(user)
        db.session.commit()

    return redirect(url_for('project_members_page', project_id=project_id))

@app.route('/projects/<int:project_id>/remove-member', methods=['POST'])
@login_required
def remove_project_member(project_id):
    if session.get('role') != 'admin':
        return "Access Denied", 403

    project = Project.query.get(project_id)
    if not project:
        return "Project not found", 404

    user_id = request.form.get('user_id')
    user = User.query.filter_by(id=user_id, role='member').first() if user_id else None
    if user and user in project.members:
        project.members.remove(user)
        db.session.commit()

    return redirect(url_for('project_members_page', project_id=project_id))

@app.route('/create_task', methods=['GET', 'POST'])
@login_required
def create_task():
    if session.get('role') != 'admin':
        return "Access Denied", 403

    projects = Project.query.all()
    project_members_map = {
        p.id: [{'id': m.id, 'name': m.name} for m in p.members]
        for p in projects
    }

    error = None
    title = ''
    description = ''
    selected_assigned_to = None
    selected_project_id = None
    deadline_str = None

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        selected_assigned_to = request.form.get('assigned_to')
        selected_project_id = request.form.get('project_id')
        deadline_str = request.form.get('due_date')

        if not title or not selected_assigned_to or not selected_project_id:
            error = 'Title, project, and assignee are required.'
        else:
            project = Project.query.get(int(selected_project_id)) if selected_project_id.isdigit() else None
            assignee = User.query.get(int(selected_assigned_to)) if selected_assigned_to.isdigit() else None

            if not project:
                error = 'Selected project is invalid.'
            elif not assignee or assignee.role != 'member':
                error = 'Selected assignee is invalid.'
            elif assignee not in project.members:
                error = 'Assignee must be a member of the selected project.'
            else:
                due_date = None
                if deadline_str:
                    try:
                        due_date = datetime.strptime(deadline_str, '%Y-%m-%d').date()
                        if due_date < date.today():
                            error = 'Due date must not be in the past.'
                    except ValueError:
                        error = 'Invalid due date format.'

        if not error:
            task = Task(
                title=title,
                description=description,
                status='To Do',
                assigned_to=int(selected_assigned_to),
                project_id=int(selected_project_id),
                due_date=due_date
            )
            db.session.add(task)
            db.session.commit()
            return redirect(url_for('dashboard'))

    return render_template(
        'create_task.html',
        projects=projects,
        error=error,
        selected_assigned_to=selected_assigned_to,
        selected_project_id=selected_project_id,
        title=title,
        description=description,
        due_date=deadline_str,
        project_members_map=project_members_map
    )

@app.route('/update_task/<int:id>/<status>')
@login_required
def update_task(id, status):
    task = Task.query.get(id)
    if not task:
        return "Task not found", 404

    allowed_statuses = ['To Do', 'In Progress', 'Completed']
    if status not in allowed_statuses:
        return 'Invalid status', 400

    if session.get('role') != 'admin' and task.assigned_to != session.get('user_id'):
        return 'Access denied', 403

    task.status = status
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/api/auth/register', methods=['POST'])
def api_auth_register():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    role = data.get('role')

    if not name or not email or not password or role not in ['admin', 'member']:
        return jsonify({'error': 'All fields are required and role must be admin or member.'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered.'}), 400

    user = User(name=name, email=email, password=generate_password_hash(password), role=role)
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'Registered successfully', 'id': user.id}), 201

@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    user = User.query.filter_by(email=email).first()
    if user and check_password_hash(user.password, password):
        session['user_id'] = user.id
        session['role'] = user.role
        return jsonify({'message': 'Logged in successfully'}), 200

    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/auth/logout', methods=['POST'])
@api_login_required
def api_auth_logout():
    session.clear()
    return jsonify({'message': 'Logged out successfully'}), 200

@app.route('/api/users', methods=['GET'])
@api_login_required
def api_users():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Access denied'}), 403

    users = User.query.all()
    return jsonify([{'id': u.id, 'name': u.name, 'email': u.email, 'role': u.role} for u in users])

@app.route('/api/projects', methods=['GET', 'POST'])
@api_login_required
def api_projects():
    if request.method == 'POST':
        if session.get('role') != 'admin':
            return jsonify({'error': 'Access denied'}), 403

        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        description = (data.get('description') or '').strip()

        if not name:
            return jsonify({'error': 'Project name is required.'}), 400

        project = Project(name=name, description=description, created_by=session['user_id'])
        db.session.add(project)
        db.session.commit()
        return jsonify({'message': 'Project created', 'id': project.id}), 201

    if session.get('role') == 'admin':
        projects = Project.query.all()
    else:
        projects = Project.query.filter(Project.members.any(id=session['user_id'])).all()

    data = [{
        'id': p.id,
        'name': p.name,
        'description': p.description,
        'created_by': p.creator.name if p.creator else None,
        'members': [{'id': u.id, 'name': u.name} for u in p.members]
    } for p in projects]
    return jsonify(data)

@app.route('/api/projects/<int:project_id>/members', methods=['GET'])
@api_login_required
@admin_required
def api_project_members(project_id):
    project = Project.query.get(project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    members = [{'id': u.id, 'name': u.name, 'email': u.email} for u in project.members]
    available = [{'id': u.id, 'name': u.name, 'email': u.email} for u in User.query.filter_by(role='member').all()]
    return jsonify({'project_id': project.id, 'members': members, 'available_members': available})

@app.route('/api/projects/<int:project_id>/add-member', methods=['POST'])
@api_login_required
@admin_required
def api_add_project_member(project_id):
    project = Project.query.get(project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    data = request.get_json() or {}
    user_id = data.get('user_id')
    user = User.query.filter_by(id=user_id, role='member').first()
    if not user:
        return jsonify({'error': 'User not found or invalid member'}), 400

    if user not in project.members:
        project.members.append(user)
        db.session.commit()

    return jsonify({'message': 'Member added'}), 200

@app.route('/api/projects/<int:project_id>/remove-member', methods=['POST'])
@api_login_required
@admin_required
def api_remove_project_member(project_id):
    project = Project.query.get(project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    data = request.get_json() or {}
    user_id = data.get('user_id')
    user = User.query.filter_by(id=user_id, role='member').first()
    if not user:
        return jsonify({'error': 'User not found or invalid member'}), 400

    if user in project.members:
        project.members.remove(user)
        db.session.commit()

    return jsonify({'message': 'Member removed'}), 200

@app.route('/api/tasks', methods=['GET', 'POST'])
@api_login_required
def api_tasks():
    if request.method == 'POST':
        if session.get('role') != 'admin':
            return jsonify({'error': 'Access denied'}), 403

        data = request.get_json() or {}
        title = (data.get('title') or '').strip()
        project_id = data.get('project_id')
        assigned_to = data.get('assigned_to')
        due_date = data.get('due_date')
        description = data.get('description', '').strip()

        project = Project.query.get(project_id)
        assignee = User.query.get(assigned_to)
        if not title or not project or not assignee:
            return jsonify({'error': 'Title, project, and valid assignee are required.'}), 400
        if assignee.role != 'member' or assignee not in project.members:
            return jsonify({'error': 'Assignee must be a project team member.'}), 400

        parsed_due_date = None
        if due_date:
            try:
                parsed_due_date = datetime.strptime(due_date, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'error': 'Invalid due date format.'}), 400

        task = Task(
            title=title,
            description=description,
            status='To Do',
            assigned_to=assigned_to,
            project_id=project_id,
            due_date=parsed_due_date
        )
        db.session.add(task)
        db.session.commit()
        return jsonify({'message': 'Task created', 'id': task.id}), 201

    if session.get('role') == 'admin':
        tasks = Task.query.all()
    else:
        tasks = Task.query.filter_by(assigned_to=session['user_id']).all()

    data = [{
        'id': t.id,
        'title': t.title,
        'description': t.description,
        'status': t.status,
        'assigned_to': t.assignee.name if t.assignee else None,
        'project': t.project.name if t.project else None,
        'due_date': t.due_date.isoformat() if t.due_date else None
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

    data = request.get_json() or {}
    if 'status' in data and data['status'] in ['To Do', 'In Progress', 'Completed']:
        task.status = data['status']
        db.session.commit()
        return jsonify({'message': 'Task updated'}), 200

    return jsonify({'error': 'Invalid data'}), 400


# create tables for Railway (IMPORTANT FIX)
with app.app_context():
    db.create_all()

    if db.engine.dialect.name == 'sqlite':
        conn = db.engine.connect()
        try:
            project_info = conn.execute(text("PRAGMA table_info(project)"))
            project_columns = {row[1] for row in project_info}
            if 'description' not in project_columns:
                conn.execute(text("ALTER TABLE project ADD COLUMN description TEXT"))

            task_info = conn.execute(text("PRAGMA table_info(task)"))
            task_columns = {row[1] for row in task_info}
            if 'due_date' not in task_columns:
                conn.execute(text("ALTER TABLE task ADD COLUMN due_date DATE"))
            if 'description' not in task_columns:
                conn.execute(text("ALTER TABLE task ADD COLUMN description TEXT"))
        finally:
            conn.close()

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
