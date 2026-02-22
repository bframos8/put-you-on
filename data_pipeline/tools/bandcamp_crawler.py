import json
import re
import time
from playwright.sync_api import sync_playwright

class BandcampCrawler:
    def __init__(self, start_url: str):
        self.DISCOVER_API = re.compile(r"/api/discover/\d+/discover_(mobile_)?web")
        self.header = "Mozilla/5.0"
        self.browser = None
        self.page = None
        self.start_url = start_url
        self.playwright = None
        self.discover_payloads = []
        self.click_times = []  # Track timing for each successful click
        
    def run(self) -> None:
        self.__start_browser()
        self._navigate_to_url()
        self._crawl()
        self._end_browser()
    
    def get_discover_payloads(self) -> list:
        return self.discover_payloads

    def __start_browser(self) -> None:
        # Initialize Playwright, launch the browser, and set up page event listeners
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch()
        self.page = self.browser.new_page()
        self.page.on("response", self._on_response)
        self.page.set_extra_http_headers({"User-Agent": self.header})
        
    def _navigate_to_url(self) -> None:
        self.page.goto(self.start_url)
        self.page.wait_for_load_state("networkidle")
        
    def _crawl(self) -> None:
        num_of_errors, num_of_success = 0, 0
        exp_backoff_factor = 0
        execution_time = 0
        backoff_time = 500
        stale_count = 0
        max_stale_attempts = 100
        prev_payload_count = 0

        while len(self.discover_payloads) < 100:
            print(f'Prev payload: {prev_payload_count}')
            print(f'Current payload: {len(self.discover_payloads)}')
            prev_payload_count = len(self.discover_payloads)
            status, execution_time = self._click_more_button()

            if status:
                num_of_success += 1
                self.click_times.append(execution_time)
                print(f"SUCCESS {num_of_success}: Waited {execution_time:.4f} seconds")

                # Check for stale content
                print(f'Prev payload: {prev_payload_count}')
                print(f'Current payload: {len(self.discover_payloads)}')
                if prev_payload_count == len(self.discover_payloads):
                    stale_count += 1
                    print(f"WARNING: No new content loaded ({stale_count}/{max_stale_attempts})")
                    if stale_count >= max_stale_attempts:
                        print("Exiting gracefully: No new content after multiple attempts")
                        break
                else:
                    stale_count = 0  # Reset on new content

                if execution_time > exp_backoff_factor * 2:
                    print(f"Backing off with factor of {exp_backoff_factor}")
                    backoff_time = (2 ** exp_backoff_factor) * 1000
                    if exp_backoff_factor < 5:
                        exp_backoff_factor += 1
                self._check_session()
                self.page.wait_for_timeout(backoff_time)

            else:
                num_of_errors += 1
                print(f"ERROR {num_of_errors}: view-more not found in {execution_time} seconds")
                print("Waiting 10 seconds and trying again")
                self.page.wait_for_timeout(10000)

        self._print_timing_stats()

    def _click_more_button(self) -> tuple[bool, float]:
        start_time = time.perf_counter()
        load_more_button = self.page.locator('#view-more')
        if load_more_button.is_visible():
            with self.page.expect_response(self.DISCOVER_API):
                load_more_button.dispatch_event("click", timeout=0)
            success_execution_time = time.perf_counter() - start_time
            return True, success_execution_time
        else:
            self.page.wait_for_timeout(10000)
            fail_execution_time = time.perf_counter() - start_time
            return False, fail_execution_time
        
    def _end_browser(self) -> None:
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        
    def _on_response(self, resp) -> None:
        urrl = resp.url
        if self.DISCOVER_API.search(urrl) and resp.ok:
            try:
                #Grab the JSON data from the response
                data = resp.json()
                self._save_resp(data)
                #Extract array of album objects
                items = data.get("items", []) or data.get("results", [])
                #Add new album objects to payload list
                self.discover_payloads.extend(items)
                print(f'{len(items)} items added succesfully.')
            except ValueError:
                print(f"Response from {urrl} is not JSON or has no items.")
    
    def _check_session(self) -> None:
        print(f"Total discover payloads collected: {len(self.discover_payloads)}")
        # For demonstration, print the first 3 payloads
        #for payload in self.discover_payloads[:3]:
         #   print(json.dumps(payload, indent=4))
    
    def _save_resp(self, resp) -> None:
        with open("resp.json", 'w') as f:
            json.dump(resp, f, indent = 4)

    def _print_timing_stats(self) -> None:
        if not self.click_times:
            print("No timing data collected.")
            return

        total_time = sum(self.click_times)
        avg_time = total_time / len(self.click_times)
        min_time = min(self.click_times)
        max_time = max(self.click_times)

        print("\n--- Timing Statistics ---")
        print(f"Total clicks: {len(self.click_times)}")
        print(f"Total time: {total_time:.2f}s")
        print(f"Average time per click: {avg_time:.4f}s")
        print(f"Min: {min_time:.4f}s | Max: {max_time:.4f}s")
        print(f"Payloads collected: {len(self.discover_payloads)}")
            

