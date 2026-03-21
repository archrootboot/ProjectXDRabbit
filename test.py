from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy

# 1. Define your options
options = UiAutomator2Options()
options.platform_name = "Android"
options.udid = "emulator-5554"
options.app_package = "com.android.chrome"
options.app_activity = "com.google.android.apps.chrome.Main"
options.no_reset = True
options.full_reset = False
options.new_command_timeout = 300

# 2. Initialize the driver
driver = webdriver.Remote("http://127.0.0.1:4723", options=options)

print("Run succesfully")
driver.quit()
