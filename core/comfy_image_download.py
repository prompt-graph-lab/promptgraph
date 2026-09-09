"""Download one prepared image URL to its already selected local path.

Exceptions propagate to the caller; warnings and aggregation remain there.
"""

import urllib.request


def download_image_to_path(image_url, save_path):
    with urllib.request.urlopen(image_url) as response:
        image_data = response.read()
        with open(save_path, "wb") as f:
            f.write(image_data)
