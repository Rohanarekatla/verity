"""
eval/inject/detach_label.py
Breaks a <label>/control association.
"""
from bs4 import BeautifulSoup

def inject(html_content: str, selector: str = "label") -> str:
    soup = BeautifulSoup(html_content, 'html.parser')
    for label in soup.select(selector):
        if label.has_attr('for'):
            label['data-verity-original-for'] = label.get('for', '')
            label['for'] = "verity-broken-id"
    return str(soup)

def revert(html_content: str, selector: str = "label") -> str:
    soup = BeautifulSoup(html_content, 'html.parser')
    for label in soup.select(selector):
        if label.has_attr('data-verity-original-for'):
            label['for'] = label.get('data-verity-original-for', '')
            del label['data-verity-original-for']
    return str(soup)