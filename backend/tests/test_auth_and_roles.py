from fastapi import status
from app.db.models import User, UserRole, Project, RefreshSession
from app.core.security import get_password_hash, create_access_token


def test_public_registration_assigns_researcher_role(client):
    payload = {
        "email": "dr.smith@oncology-lab.org",
        "password": "SecurePassword123",
        "full_name": "Dr. Eleanor Smith",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["email"] == "dr.smith@oncology-lab.org"
    assert data["role"] == "RESEARCHER"
    assert "hashed_password" not in data

    # Verify cookies
    assert "nf_access_token" in response.cookies
    assert "nf_refresh_token" in response.cookies
    assert "nf_csrf_token" in response.cookies


def test_registration_duplicate_email_rejected(client):
    payload = {
        "email": "duplicate@lab.org",
        "password": "SecurePassword123",
        "full_name": "Dr. Duplicate",
    }
    r1 = client.post("/auth/register", json=payload)
    assert r1.status_code == status.HTTP_201_CREATED

    r2 = client.post("/auth/register", json=payload)
    assert r2.status_code == status.HTTP_400_BAD_REQUEST
    assert "already exists" in r2.json()["detail"]


def test_login_success_and_invalid_credentials(client, db_session):
    # Create user
    user = User(
        email="researcher@bioforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Bio Researcher",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    # Wrong password
    bad_res = client.post("/auth/login", json={
        "email": "researcher@bioforge.org",
        "password": "WrongPassword999",
    })
    assert bad_res.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Incorrect email or password" in bad_res.json()["detail"]

    # Nonexistent user
    non_res = client.post("/auth/login", json={
        "email": "ghost@bioforge.org",
        "password": "ValidPass123",
    })
    assert non_res.status_code == status.HTTP_401_UNAUTHORIZED

    # Valid login
    good_res = client.post("/auth/login", json={
        "email": "researcher@bioforge.org",
        "password": "ValidPass123",
    })
    assert good_res.status_code == status.HTTP_200_OK
    assert good_res.json()["email"] == "researcher@bioforge.org"
    assert "nf_access_token" in good_res.cookies


def test_deactivated_user_cannot_login(client, db_session):
    user = User(
        email="inactive@bioforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Inactive User",
        role=UserRole.RESEARCHER.value,
        is_active=False,
    )
    db_session.add(user)
    db_session.commit()

    res = client.post("/auth/login", json={
        "email": "inactive@bioforge.org",
        "password": "ValidPass123",
    })
    assert res.status_code == status.HTTP_403_FORBIDDEN


def test_refresh_token_rotation_and_logout(client, db_session):
    # Register to get tokens
    reg = client.post("/auth/register", json={
        "email": "rotating@lab.org",
        "password": "Pass12345Rotation",
        "full_name": "Dr. Rotation",
    })
    assert reg.status_code == status.HTTP_201_CREATED
    initial_refresh = reg.cookies.get("nf_refresh_token")
    initial_csrf = reg.cookies.get("nf_csrf_token")
    assert initial_refresh is not None
    assert initial_csrf is not None

    # Call refresh with valid CSRF verification
    ref = client.post(
        "/auth/refresh",
        cookies={"nf_refresh_token": initial_refresh, "nf_csrf_token": initial_csrf},
        headers={"X-CSRF-Token": initial_csrf},
    )
    assert ref.status_code == status.HTTP_200_OK
    new_refresh = ref.cookies.get("nf_refresh_token")
    new_csrf = ref.cookies.get("nf_csrf_token") or initial_csrf
    assert new_refresh is not None
    assert new_refresh != initial_refresh

    # Old refresh token should now be rejected (revoked)
    client.cookies.clear()
    stale_ref = client.post(
        "/auth/refresh",
        cookies={"nf_refresh_token": initial_refresh, "nf_csrf_token": new_csrf},
        headers={"X-CSRF-Token": new_csrf},
    )
    assert stale_ref.status_code == status.HTTP_401_UNAUTHORIZED

    # Logout revokes the session
    client.cookies.clear()
    logout_res = client.post(
        "/auth/logout",
        cookies={"nf_refresh_token": new_refresh, "nf_csrf_token": new_csrf},
        headers={"X-CSRF-Token": new_csrf},
    )
    assert logout_res.status_code == status.HTTP_200_OK

    # Attempting to refresh with the logged-out token fails
    client.cookies.clear()
    after_logout = client.post(
        "/auth/refresh",
        cookies={"nf_refresh_token": new_refresh, "nf_csrf_token": new_csrf},
        headers={"X-CSRF-Token": new_csrf},
    )
    assert after_logout.status_code == status.HTTP_401_UNAUTHORIZED


def test_auth_me_protected_route(client, db_session):
    # Without cookie or header -> 401
    unauth = client.get("/auth/me")
    assert unauth.status_code == status.HTTP_401_UNAUTHORIZED

    # Register user
    reg = client.post("/auth/register", json={
        "email": "profile@lab.org",
        "password": "Password12345",
        "full_name": "Profile Owner",
    })
    access_token = reg.cookies.get("nf_access_token")

    # With cookie
    auth_res = client.get("/auth/me", cookies={"nf_access_token": access_token})
    assert auth_res.status_code == status.HTTP_200_OK
    assert auth_res.json()["email"] == "profile@lab.org"

    # With Authorization header
    header_res = client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert header_res.status_code == status.HTTP_200_OK
    assert header_res.json()["email"] == "profile@lab.org"


def test_role_authorization_and_admin_protections(client, db_session):
    # Create 1 Admin, 1 Researcher, 1 Viewer
    admin = User(
        email="admin@neuroforge.org",
        hashed_password=get_password_hash("AdminPass123"),
        full_name="Lead Admin",
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    researcher = User(
        email="res@neuroforge.org",
        hashed_password=get_password_hash("ResPass123"),
        full_name="Active Researcher",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    viewer = User(
        email="view@neuroforge.org",
        hashed_password=get_password_hash("ViewPass123"),
        full_name="Read-Only Viewer",
        role=UserRole.VIEWER.value,
        is_active=True,
    )
    db_session.add_all([admin, researcher, viewer])
    db_session.commit()

    admin_token = create_access_token(admin.id, admin.role)
    res_token = create_access_token(researcher.id, researcher.role)
    view_token = create_access_token(viewer.id, viewer.role)

    # 1. User management listing: ADMIN allowed, Researcher & Viewer forbidden (403)
    assert client.get("/users", headers={"Authorization": f"Bearer {admin_token}"}).status_code == 200
    assert client.get("/users", headers={"Authorization": f"Bearer {res_token}"}).status_code == 403
    assert client.get("/users", headers={"Authorization": f"Bearer {view_token}"}).status_code == 403

    # 2. Last active admin protection: Cannot demote or deactivate the only admin
    csrf_token = "valid-csrf"
    demote_res = client.patch(
        f"/users/{admin.id}/role",
        json={"role": "RESEARCHER"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert demote_res.status_code == status.HTTP_400_BAD_REQUEST
    assert "last active system administrator" in demote_res.json()["detail"]

    deactivate_res = client.patch(
        f"/users/{admin.id}/status",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert deactivate_res.status_code == status.HTTP_400_BAD_REQUEST
    assert "last active system administrator" in deactivate_res.json()["detail"]

    # 3. Project Creation: ADMIN and RESEARCHER allowed, VIEWER forbidden (403)
    p_res = client.post(
        "/projects",
        json={"title": "Researcher Project", "description": "Studying RNA-seq"},
        headers={"Authorization": f"Bearer {res_token}"},
    )
    assert p_res.status_code == status.HTTP_201_CREATED
    project_id = p_res.json()["id"]

    p_view = client.post(
        "/projects",
        json={"title": "Viewer Attempt", "description": "Should fail"},
        headers={"Authorization": f"Bearer {view_token}"},
    )
    assert p_view.status_code == status.HTTP_403_FORBIDDEN

    # 4. Project Modification Ownership:
    # Another researcher cannot edit researcher's project
    other_res = User(
        email="other@neuroforge.org",
        hashed_password=get_password_hash("Pass12345"),
        full_name="Other Researcher",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(other_res)
    db_session.commit()
    other_token = create_access_token(other_res.id, other_res.role)

    edit_unauth = client.put(
        f"/projects/{project_id}",
        json={"title": "Tampered Title"},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert edit_unauth.status_code == status.HTTP_403_FORBIDDEN

    # Owner can edit
    edit_owner = client.put(
        f"/projects/{project_id}",
        json={"title": "Updated by Owner"},
        headers={"Authorization": f"Bearer {res_token}"},
    )
    assert edit_owner.status_code == status.HTTP_200_OK
    assert edit_owner.json()["title"] == "Updated by Owner"

    # Admin can edit or delete
    del_admin = client.delete(
        f"/projects/{project_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_admin.status_code == status.HTTP_200_OK


def test_overview_stats_honest_counts(client, db_session):
    user = User(
        email="stats@neuroforge.org",
        hashed_password=get_password_hash("StatsPass123"),
        full_name="Stats Researcher",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(user.id, user.role)

    stats = client.get("/overview/stats", headers={"Authorization": f"Bearer {token}"})
    assert stats.status_code == 200
    data = stats.json()
    assert data["projects_count"] == 0
    assert data["datasets_count"] == 0
    assert data["experiments_count"] == 0
    assert data["reports_count"] == 0

