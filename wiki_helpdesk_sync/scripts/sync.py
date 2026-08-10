import frappe
from bs4 import BeautifulSoup
from frappe.frappeclient import FrappeClient

from wiki_helpdesk_sync.wiki_helpdesk_sync.doctype.helpdesk_settings.helpdesk_settings import HelpdeskSettings


def get_or_create_hd_category(page_name):
	"""Finds category of wiki page from child table"""
	global client
	category = frappe.db.get_value(
		"Wiki Group Item",
		{"wiki_page": page_name, "parent": "7ncdodb8sb"},
		"parent_label",  # /cloud wiki space
	)
	if not category:
		return

	hd_category = client.get_value(
		"HD Article Category",
		"name",
		{"category_name": category},
	)  # Frappe Cloud children

	if not hd_category:
		# print(f"{category} doesn't exist")
		doc_dict = {
			"doctype": "HD Article Category",
			"category_name": category,
		}
		hd_category = client.insert(doc_dict)
	return hd_category["name"]


def move_images_outside_para(html: str):
	soup = BeautifulSoup(html, "html.parser")
	images = soup.find_all("img")
	for img in images:
		source = img.parent
		if not source:
			continue
		if source.name != "p":
			continue
		before_para = soup.new_tag("p")
		before = list(img.previous_siblings)
		before.reverse()
		for element in before:
			before_para.append(element)
		after_para = soup.new_tag("p")
		after = list(img.next_siblings)
		for element in after:
			after_para.append(element)
		source.insert_before(before_para)
		source.insert_before(img)
		source.insert_before(after_para)
		source.decompose()

	return str(soup)


def fix_images(html: str):
	"""img tags need to be manipulated cuz text editors aren't standardized even in 2023"""
	html = html.replace('src="/', 'src="https://frappecloud.com/')
	html = html.replace('class="screenshot"', "")
	return move_images_outside_para(html)


def get_html(content: str) -> str:
	if frappe.utils.is_markdown(content):
		content = frappe.utils.md_to_html(content)
		content = content.replace("<!-- markdown -->", "")
	return frappe.utils.sanitize_html(content, linkify=True)


def normalize_html(html: str) -> str:
	"""Helpdesk re-sanitizes content on save (e.g. adds rel to anchors), so ignore that while comparing"""
	soup = BeautifulSoup(html or "", "html.parser")
	for anchor in soup.find_all("a"):
		anchor.attrs.pop("rel", None)
	return str(soup)


def needs_update(hd_article, doc_dict) -> bool:
	for key, value in doc_dict.items():
		if key == "content":
			if normalize_html(hd_article.get(key)) != normalize_html(value):
				return True
		elif hd_article.get(key) != value:
			return True
	return False


def main():
	settings = HelpdeskSettings("Helpdesk Settings")
	if not settings.api_key or not settings.api_secret or not settings.site_url:
		return
	global client
	client = FrappeClient(
		settings.site_url, api_key=settings.api_key, api_secret=settings.get_password("api_secret")
	)

	public_wiki_pages = frappe.get_all(
		"Wiki Page", filters={"published": 1, "allow_guest": 1, "route": ("like", "%cloud%")}
	)

	doctype = "HD Article"
	for page in public_wiki_pages:
		wiki_page = frappe.get_doc("Wiki Page", page.name)

		doc_dict = {
			"doctype": doctype,
			"title": wiki_page.title,
			"content": fix_images(get_html(wiki_page.content)),
			"category": get_or_create_hd_category(page.name),
			"status": "Published",
		}
		if doc_dict["category"] is None:
			continue
		hd_article = client.get_value(
			doctype, "name", {"title": wiki_page.title, "category": doc_dict["category"]}
		)
		if not hd_article:
			hd_article = client.insert(doc_dict)
		else:
			doc_dict.pop("doctype")
			hd_article = client.get_doc("HD Article", hd_article["name"])
			if not needs_update(hd_article, doc_dict):
				continue
			for key, value in doc_dict.items():
				hd_article[key] = value
			client.update(hd_article)
