"""
HTML Parser Module for Web Crawler

This module provides functions for:
- Detecting HTML content
- Extracting and normalizing links from HTML
- Domain validation and comparison
"""

from bs4 import BeautifulSoup, SoupStrainer
from urllib.parse import urlsplit
from .utils import normalize_url

def is_html_content(headers: dict) -> bool:
    """
    Check if response headers indicate HTML content.
    
    Args:
        headers (dict): HTTP response headers
        
    Returns:
        bool: True if content type is HTML
    """
    ct = headers.get('Content-Type') or headers.get('content-type') or ''
    return 'text/html' in ct.lower()

def extract_links(base_url: str, html: bytes, max_links: int = 1000):
    """
    Extract and normalize links from HTML content with safety limits.
    
    Features:
    - Memory-efficient parsing using SoupStrainer
    - URL normalization and validation
    - Configurable link limit
    - URL length validation
    
    Args:
        base_url (str): Base URL for resolving relative links
        html (bytes): Raw HTML content
        max_links (int): Maximum number of links to extract (default: 1000)
        
    Returns:
        list: List of normalized URLs found in the HTML
    """
    only_a_tags = SoupStrainer('a')  # Memory optimization: parse only <a> tags
    soup = BeautifulSoup(html, 'html.parser', parse_only=only_a_tags)
    hrefs = []
    
    for a in soup.find_all('a', href=True):
        if len(hrefs) >= max_links:
            break
        try:
            normalized_url = normalize_url(base_url, a['href'])
            if normalized_url and len(normalized_url) < 2048:  # Enforce URL length limit
                hrefs.append(normalized_url)
        except Exception:
            continue
    return hrefs

def same_reg_domain(url: str, allowed, follow_subdomains: bool = True) -> bool:
    """
    Check if a URL belongs to an allowed domain.
    
    Supports both exact domain matching and subdomain matching.
    
    Args:
        url (str): URL to check
        allowed (str or list): Allowed domain(s)
        follow_subdomains (bool): If True, allow subdomains of allowed domains
        
    Returns:
        bool: True if URL's domain matches allowed domain(s)
        
    Examples:
        >>> same_reg_domain('https://sub.example.com', 'example.com', follow_subdomains=True)
        True
        >>> same_reg_domain('https://other.com', 'example.com', follow_subdomains=False)
        False
    """
    host = urlsplit(url).netloc.lower()
    if isinstance(allowed, str):
        allowed = [allowed]
        
    for domain in allowed:
        if follow_subdomains:
            if host.endswith(domain):  # Match domain and its subdomains
                return True
        else:
            if host == domain:  # Match exact domain only
                return True
    return False

