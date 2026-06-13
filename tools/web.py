import requests
from bs4 import BeautifulSoup
import urllib.parse
import time

class WebTools:
    @staticmethod
    def web_search(query, num_results=5):
        """Searches the web using DuckDuckGo and returns a list of result titles and URLs."""
        try:
            # We use the DuckDuckGo HTML version which is easier to scrape
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://duckduckgo.com/'
            }
            
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            results = []
            
            # Find all result containers
            result_containers = soup.find_all('div', class_='result')
            
            for i, container in enumerate(result_containers):
                if i >= num_results:
                    break
                    
                title_tag = container.find('a', class_='result__a')
                snippet_tag = container.find('a', class_='result__snippet')
                
                if title_tag:
                    title = title_tag.get_text(strip=True)
                    link = title_tag.get('href')
                    
                    # Clean up the link if it's a redirect
                    if link and link.startswith('//'):
                        link = 'https:' + link
                    
                    if link and '/l/?' in link and 'uddg=' in link:
                        try:
                            import re
                            match = re.search(r'uddg=([^&]+)', link)
                            if match:
                                link = urllib.parse.unquote(match.group(1))
                        except Exception:
                            pass
                        
                    snippet = snippet_tag.get_text(strip=True) if snippet_tag else "No description available."
                    
                    results.append(f"Title: {title}\nURL: {link}\nDescription: {snippet}\n")
            
            if not results:
                return "No results found. The search engine might be blocking the request or the query returned nothing."
                
            return "\n".join(results)
        except Exception as e:
            return f"Error during web search: {e}"

    @staticmethod
    def scrape_content(url):
        """Scrapes the main text content from a given URL."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()

            # Get text
            text = soup.get_text()

            # Break into lines and remove leading and trailing whitespace
            lines = (line.strip() for line in text.splitlines())
            # Break multi-headlines into a line each
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            # Drop blank lines
            text = '\n'.join(chunk for chunk in chunks if chunk)

            # Limit text length to avoid context overflow
            return text[:5000] + "..." if len(text) > 5000 else text
        except Exception as e:
            return f"Error during scraping: {e}"

def get_tool_map():
    """Returns a map of tool names to their functions."""
    return {
        "web_search": WebTools.web_search,
        "scrape_content": WebTools.scrape_content
    }
