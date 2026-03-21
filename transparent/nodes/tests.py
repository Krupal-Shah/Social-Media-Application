from django.test import TestCase
from nodes.models import Node
from authors.models import Author

class NodeModelTests(TestCase):
    def test_can_create_node_and_defaults_active_true(self):
        node = Node.objects.create(
            base_url="https://remote.example/api/",
            username="u",
            password="p",
        )
        self.assertTrue(node.active)

class NodeAdminTests(TestCase):
    def setUp(self):
        # Create a superuser (Node Admin) for our tests
        self.admin_user = Author.objects.create_user(
            username="nodeadmin",
            password="supersecretpassword",
            display_name="The Node Admin",
            host="http://testserver/api/"
        )
        self.admin_user.is_staff = True
        self.admin_user.is_superuser = True
        self.admin_user.save()
        
        # Log the admin in
        self.client.login(username="nodeadmin", password="supersecretpassword")

    def test_node_admin_page_loads(self):
        """Test that the Node admin list page loads successfully for an admin."""
        resp = self.client.get("/admin/nodes/node/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Select node to change")

    def test_admin_can_create_node_via_panel(self):
        """Test that an admin can create a remote node purely through the Django admin form."""
        resp = self.client.post("/admin/nodes/node/add/", {
            "base_url": "https://team-yoshi.herokuapp.com/api/",
            "username": "yoshi_user",
            "password": "yoshi_password",
            "active": "on",  # This is how HTML checkboxes send 'True'
        })
        
        # A successful form submission in Django Admin returns a 302 redirect back to the list
        self.assertEqual(resp.status_code, 302)
        
        # Verify it was actually saved to the database!
        self.assertTrue(
            Node.objects.filter(base_url="https://team-yoshi.herokuapp.com/api/").exists()
        )

    def test_non_admin_cannot_access_nodes(self):
        """Test that standard users are blocked from seeing the remote nodes."""
        # Log out the admin and log in a regular user
        self.client.logout()
        regular_user = Author.objects.create_user(
            username="regular",
            password="password123",
            display_name="Regular User",
            host="http://testserver/api/"
        )
        self.client.login(username="regular", password="password123")
        
        resp = self.client.get("/admin/nodes/node/")
        
        # Should redirect them to the admin login page because they lack staff status
        self.assertRedirects(resp, "/admin/login/?next=/admin/nodes/node/", fetch_redirect_response=False)