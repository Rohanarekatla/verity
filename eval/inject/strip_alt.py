"""
eval/inject/strip_alt.py
Removes `alt` text from an image.
"""
from bs4 import BeautifulSoup

def inject(html_content: str, selector: str = "img") -> str:
    soup = BeautifulSoup(html_content, 'html.parser')
    for element in soup.select(selector):
        if element.has_attr('alt'):
            element['data-verity-original-alt'] = element.get('alt', '')
            del element['alt']
    return str(soup)

def revert(html_content: str, selector: str = "img") -> str:
    soup = BeautifulSoup(html_content, 'html.parser')
    for element in soup.select(selector):
        if element.has_attr('data-verity-original-alt'):
            element['alt'] = element.get('data-verity-original-alt', '')
            del element['data-verity-original-alt']
    return str(soup)