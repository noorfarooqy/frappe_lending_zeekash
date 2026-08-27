app_name = "frappe_lending_zeekash"
app_title = "Frappe Lending Zeekash Bridge"
app_publisher = "Captain"
app_description = "Zeekash financier adapter for Frappe Lending"
app_email = "noordrongo@gmail.com"
app_license = "mit"

# Serve zeekash's canonical financier contract (/oauth/token, /financing/*) directly
# from this Frappe site, so the stock CanonicalFinancingConnector reaches it with no
# bespoke code in zeekash. See frappe_lending_zeekash/router.py.
page_renderer = ["frappe_lending_zeekash.router.FinancingRouter"]

# Add the Murabaha profit-rate custom field to Loan Product (never edits the lending app).
after_migrate = "frappe_lending_zeekash.install.after_migrate"

# Financier-driven status: as isnaad operates the loan in Frappe (disburse, repay, close),
# fire the matching webhook to zeekash. Only zeekash-originated loans are touched.
doc_events = {
	"Loan Disbursement": {"on_submit": "frappe_lending_zeekash.events.on_loan_disbursement_submit"},
	"Loan Repayment": {"on_submit": "frappe_lending_zeekash.events.on_loan_repayment_submit"},
	"Loan": {
		"on_update_after_submit": "frappe_lending_zeekash.events.on_loan_update",
		"on_cancel": "frappe_lending_zeekash.events.on_loan_cancel",
	},
}

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "frappe_lending_zeekash",
# 		"logo": "/assets/frappe_lending_zeekash/logo.png",
# 		"title": "Frappe Lending Zeekash Bridge",
# 		"route": "/frappe_lending_zeekash",
# 		"has_permission": "frappe_lending_zeekash.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/frappe_lending_zeekash/css/frappe_lending_zeekash.css"
# app_include_js = "/assets/frappe_lending_zeekash/js/frappe_lending_zeekash.js"

# include js, css files in header of web template
# web_include_css = "/assets/frappe_lending_zeekash/css/frappe_lending_zeekash.css"
# web_include_js = "/assets/frappe_lending_zeekash/js/frappe_lending_zeekash.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "frappe_lending_zeekash/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "frappe_lending_zeekash/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "frappe_lending_zeekash.utils.jinja_methods",
# 	"filters": "frappe_lending_zeekash.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "frappe_lending_zeekash.install.before_install"
# after_install = "frappe_lending_zeekash.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "frappe_lending_zeekash.uninstall.before_uninstall"
# after_uninstall = "frappe_lending_zeekash.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "frappe_lending_zeekash.utils.before_app_install"
# after_app_install = "frappe_lending_zeekash.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "frappe_lending_zeekash.utils.before_app_uninstall"
# after_app_uninstall = "frappe_lending_zeekash.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "frappe_lending_zeekash.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "frappe_lending_zeekash.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["frappe_lending_zeekash.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"frappe_lending_zeekash.tasks.all"
# 	],
# 	"daily": [
# 		"frappe_lending_zeekash.tasks.daily"
# 	],
# 	"hourly": [
# 		"frappe_lending_zeekash.tasks.hourly"
# 	],
# 	"weekly": [
# 		"frappe_lending_zeekash.tasks.weekly"
# 	],
# 	"monthly": [
# 		"frappe_lending_zeekash.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "frappe_lending_zeekash.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "frappe_lending_zeekash.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "frappe_lending_zeekash.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "frappe_lending_zeekash.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["frappe_lending_zeekash.utils.before_request"]
# after_request = ["frappe_lending_zeekash.utils.after_request"]

# Job Events
# ----------
# before_job = ["frappe_lending_zeekash.utils.before_job"]
# after_job = ["frappe_lending_zeekash.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"frappe_lending_zeekash.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

