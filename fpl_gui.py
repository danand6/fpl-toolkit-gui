import customtkinter
import fpl_logic  # Our refactored logic file
import threading
import requests
import json

customtkinter.set_appearance_mode("System")  # Modes: "System" (default), "Dark", "Light"
customtkinter.set_default_color_theme("blue")  # Themes: "blue" (default), "green", "dark-blue"

class FPLApp(customtkinter.CTk):
    def __init__(self):
        super().__init__()

        # --- Window Setup ---
        self.title("FPL Toolkit")
        self.geometry("1200x750")

        # --- Layout Configuration ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1) # Make the main container fill the window

        # --- App State ---
        self.team_id = None
        self.league_id = None
        self.bootstrap_data = None
        self.fixtures_data = None
        self.player_map = None
        self.team_map = None
        self.position_map = None
        self.current_gameweek = None

        # --- Widget Placeholders ---
        self.login_frame = None
        self.main_frame = None # New frame to hold the main app UI
        self.sidebar_frame = None
        self.tab_view = None
        self.status_label = None
        self.buttons = {}

        # --- Create main frames ---
        self.create_login_screen()
        self.create_main_ui_frame()

        # --- Start the application flow ---
        self.initialize_app()

    def initialize_app(self):
        """Checks for existing config and decides whether to show login or main app."""
        try:
            team_id, league_id = fpl_logic.load_or_create_config()
            if team_id != 1 and league_id != 1: # Check for valid, non-placeholder IDs
                self.handle_login(team_id, league_id, is_initial_load=True)
            else:
                self.switch_to_login_frame()
        except Exception:
            self.switch_to_login_frame()

    def create_login_screen(self):
        """Displays the login UI for entering IDs."""
        self.login_frame = customtkinter.CTkFrame(self)
        # This frame will be placed and removed from the grid as needed

        # Use an inner frame to center the content
        center_frame = customtkinter.CTkFrame(self.login_frame, fg_color="transparent")
        center_frame.place(relx=0.5, rely=0.5, anchor="center")

        title_label = customtkinter.CTkLabel(center_frame, text="FPL Toolkit", font=customtkinter.CTkFont(size=36, weight="bold"))
        title_label.pack(padx=30, pady=(0, 50))

        self.team_id_entry = customtkinter.CTkEntry(center_frame, placeholder_text="Enter your Team ID", width=250)
        self.team_id_entry.pack(padx=30, pady=10)

        self.league_id_entry = customtkinter.CTkEntry(center_frame, placeholder_text="Enter your League ID", width=250)
        self.league_id_entry.pack(padx=30, pady=10)

        login_button = customtkinter.CTkButton(center_frame, text="Continue", command=self.on_login_button_press, width=250)
        login_button.pack(padx=30, pady=(20, 10))

        self.login_status_label = customtkinter.CTkLabel(center_frame, text="", text_color="red")
        self.login_status_label.pack(padx=30, pady=10)

    def on_login_button_press(self):
        """Validates input and triggers the login process."""
        try:
            team_id = int(self.team_id_entry.get())
            league_id = int(self.league_id_entry.get())
            self.login_status_label.configure(text="Verifying details...", text_color=("black", "white"))
            self.handle_login(team_id, league_id)
        except (ValueError, TypeError):
            self.login_status_label.configure(text="Invalid input. Please enter numbers only for IDs.", text_color="red")

    def create_main_ui_frame(self):
        """Creates the main application frame and its widgets. This is done only once."""
        self.main_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid_columnconfigure(1, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1)

        # --- Sidebar Frame for Buttons ---
        self.sidebar_frame = customtkinter.CTkFrame(self.main_frame, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(12, weight=1)

        self.logo_label = customtkinter.CTkLabel(self.sidebar_frame, text="", font=customtkinter.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        # --- Main Content Display (Tab View) ---
        self.tab_view = customtkinter.CTkTabview(self.main_frame, width=250)
        self.tab_view.grid(row=0, column=1, padx=(20, 20), pady=(20, 0), sticky="nsew")

        # Add a default "Home" tab
        self.tab_view.add("Home")
        home_label = customtkinter.CTkLabel(self.tab_view.tab("Home"), text="Welcome to the FPL Toolkit!\n\nSelect an option from the sidebar to get started.", font=customtkinter.CTkFont(size=16))
        home_label.place(relx=0.5, rely=0.5, anchor="center")
        self.tab_view.set("Home") # Set it as the active tab
        self._tab_textboxes = {} # To store textboxes for each feature tab

        # --- Status Bar ---
        self.status_label = customtkinter.CTkLabel(self.main_frame, text="Ready", anchor="w")
        self.status_label.grid(row=1, column=1, padx=20, pady=(5, 10), sticky="ew")

    def create_buttons(self):
        """Creates all the feature buttons in the sidebar."""
        # This dictionary now holds all the information needed to create a button.
        # The 'args' key is a tuple of arguments to pass to the logic function.
        button_definitions = {
            "My Team Summary": lambda: self.run_feature("My Team Summary",
                fpl_logic.get_my_team_summary_string, (self.team_id, self.current_gameweek, self.player_map)
            ),
            "Smart Captaincy": lambda: self.run_feature("Smart Captaincy",
                fpl_logic.get_captaincy_suggester_string, (self.team_id, self.current_gameweek, self.bootstrap_data, self.fixtures_data)
            ),
            "Clear Output": self.clear_current_tab,
            "Differential Hunter": "dropdown", # Special case for dropdown
            "Transfer Suggester": lambda: self.run_feature("Transfer Suggester",
                fpl_logic.get_transfer_suggester_string, (self.team_id, self.current_gameweek, self.bootstrap_data, self.fixtures_data, self.team_map, self.position_map)
            ),
            "Predict Top Performers": lambda: self.run_feature("Top Performers",
                fpl_logic.get_predicted_points_data, (self.bootstrap_data, self.fixtures_data, self.current_gameweek)
            ),
            "Dream Team Optimizer": lambda: self.run_feature("Dream Team",
                fpl_logic.get_dream_team_optimizer_string, (self.bootstrap_data, self.fixtures_data, self.current_gameweek, self.position_map)
            ),
            "League Predictions": lambda: self.run_feature("League Predictions",
                fpl_logic.get_league_predictions_string, (self.league_id, self.current_gameweek, self.bootstrap_data, self.fixtures_data)
            ),
            "Injury/Risk Analyzer": lambda: self.run_feature("Injury/Risk",
                fpl_logic.get_injury_risk_analyzer_string, (self.bootstrap_data, self.team_map)
            ),
            "Quadrant Analysis": lambda: self.run_feature("Quadrant Analysis",
                fpl_logic.get_quadrant_analysis_string, (self.bootstrap_data, self.fixtures_data, self.current_gameweek, self.team_map)
            ),
        }
        
        row_num = 1
        for text, command in button_definitions.items():
            if text == "Differential Hunter":
                # Create a frame to hold the label and dropdown for this feature
                diff_hunter_frame = customtkinter.CTkFrame(self.sidebar_frame)
                diff_hunter_frame.grid(row=row_num, column=0, padx=20, pady=10, sticky="ew")

                label = customtkinter.CTkLabel(diff_hunter_frame, text="Differential Hunter:", font=customtkinter.CTkFont(weight="bold"))
                label.pack(pady=(5, 0))

                # Map display text to the actual sort keys the logic function expects
                diff_options = {
                    "Sort by Form": "form",
                    "Sort by Points": "total_points",
                    "Sort by ICT": "ict_index"
                }

                def dropdown_callback(choice):
                    sort_key = diff_options[choice]
                    self.run_feature("Differential Hunter",
                        fpl_logic.get_differential_hunter_data, 
                        (self.bootstrap_data, self.team_map, self.position_map, sort_key)
                    )

                dropdown = customtkinter.CTkOptionMenu(diff_hunter_frame, values=list(diff_options.keys()), command=dropdown_callback)
                dropdown.pack(padx=10, pady=(5, 10), fill="x")
                dropdown.set("Sort by Form") # Set a default value
            else:
                self.buttons[text] = customtkinter.CTkButton(self.sidebar_frame, text=text, command=command)
                self.buttons[text].grid(row=row_num, column=0, padx=20, pady=10)
            row_num += 1

        # Add a settings button at the bottom
        self.logout_button = customtkinter.CTkButton(self.sidebar_frame, text="Log Out", command=self.log_out)
        self.logout_button.grid(row=12, column=0, padx=20, pady=20, sticky="s")

    def handle_login(self, team_id, league_id, is_initial_load=False):
        """Verifies IDs, saves them, and transitions to the main app UI."""
        def task():
            try:
                # Fetch entry data to get user's name and validate the team_id
                entry_data = fpl_logic.get_entry_data(team_id)
                if not entry_data or 'player_first_name' not in entry_data:
                     raise ValueError("Invalid Team ID or FPL API is down.")
                user_name = f"{entry_data['player_first_name']} {entry_data['player_last_name']}"

                # Save the valid config
                config = {'team_id': team_id, 'league_id': league_id}
                with open('config.json', 'w') as f:
                    json.dump(config, f, indent=4)

                self.team_id = team_id
                self.league_id = league_id

                # Update welcome message and switch to main UI
                self.after(0, self.logo_label.configure, {"text": f"Welcome,\n{user_name}!"})
                self.after(0, self.switch_to_main_frame)

                # If this is the first time loading, fetch all data.
                if is_initial_load:
                    self.after(100, self.load_all_data)

            except (requests.exceptions.RequestException, ValueError) as e:
                # If login fails, show error on the login screen
                self.after(0, self.switch_to_login_frame)
                self.after(0, lambda: self.login_status_label.configure(text=f"Login failed: {e}", text_color="red"))

        threading.Thread(target=task, daemon=True).start()

    def load_all_data(self):
        """Loads all essential FPL data in a thread after a successful login."""
        self.update_status("Loading essential FPL data...")
        # Update the home tab's label to show loading status
        home_label = self.tab_view.tab("Home").winfo_children()[0]
        home_label.configure(text="Loading essential FPL data, please wait...")

        def task():
            try:
                self.bootstrap_data = fpl_logic.get_bootstrap_data() # This is cached
                self.fixtures_data = fpl_logic.get_fixtures_data()
                self.player_map = fpl_logic.create_player_map(self.bootstrap_data)
                self.team_map = fpl_logic.create_team_map(self.bootstrap_data)
                self.position_map = fpl_logic.create_position_map(self.bootstrap_data)
                self.current_gameweek = fpl_logic.get_current_gameweek(self.bootstrap_data)

                self.after(0, self.create_buttons)
                self.after(0, self.update_status, f"Data loaded for GW {self.current_gameweek}. Ready.")
                self.after(0, home_label.configure, {"text": "Data loaded successfully.\nPlease select an option from the sidebar."})
            except Exception as e:
                self.after(0, self.update_status, "Error loading data!")
                # Update the home tab with the error
                home_label = self.tab_view.tab("Home").winfo_children()[0]
                self.after(0, home_label.configure, {"text": f"An error occurred during startup:\n\n{e}"})

        threading.Thread(target=task, daemon=True).start()

    def run_feature(self, tab_name, func, args_tuple):
        """
        Runs a logic function in a separate thread to prevent the GUI from freezing
        and displays the result in a dedicated tab.
        """
        # Create and switch to the tab for this feature
        target_tab = None
        try:
            target_tab = self.tab_view.tab(tab_name)
        except Exception:
            self.tab_view.add(tab_name)
            target_tab = self.tab_view.tab(tab_name)
        
        self.tab_view.set(tab_name)

        # Clear previous content and show loading message
        for widget in target_tab.winfo_children():
            widget.destroy()
        loading_label = customtkinter.CTkLabel(target_tab, text="Fetching data, please wait...")
        loading_label.place(relx=0.5, rely=0.5, anchor="center")

        self.status_label.configure(text=f"Running: {func.__name__}...")
        self.disable_buttons()

        def task():
            try:
                # Call the logic function with its arguments
                result_data = func(*args_tuple)
                
                # Clear loading message before rendering new content
                self.after(0, loading_label.destroy)

                # Render based on data type
                if isinstance(result_data, dict) and result_data.get("type") == "table":
                    self.after(0, self.render_table_output, target_tab, result_data)
                else: # Default to string in a textbox
                    content = result_data if isinstance(result_data, str) else str(result_data)
                    self.after(0, self.render_text_output, target_tab, content)

                self.after(0, self.update_status, "Done.")
            except Exception as e:
                error_message = f"An error occurred:\n\n{e}"
                self.after(0, loading_label.destroy)
                self.after(0, self.render_text_output, target_tab, error_message)
                self.after(0, self.update_status, "Error.")

            self.after(0, self.enable_buttons)
        # Run the task in a non-blocking thread
        threading.Thread(target=task, daemon=True).start()

    def render_text_output(self, target_tab, content):
        """Renders string output in a standard textbox."""
        textbox = customtkinter.CTkTextbox(target_tab)
        textbox.pack(fill="both", expand=True, padx=5, pady=5)
        textbox.delete("1.0", "end")
        textbox.insert("1.0", content)
        self._tab_textboxes[target_tab.winfo_name()] = textbox

    def render_table_output(self, target_tab, data):
        """Renders structured table data in a visually appealing way."""
        title_label = customtkinter.CTkLabel(target_tab, text=data.get("title", ""), font=customtkinter.CTkFont(size=18, weight="bold"))
        title_label.pack(pady=(10, 15), padx=20, anchor="w")

        scrollable_frame = customtkinter.CTkScrollableFrame(target_tab)
        scrollable_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Create Headers
        for col_idx, header_text in enumerate(data.get("headers", [])):
            header_label = customtkinter.CTkLabel(scrollable_frame, text=header_text, font=customtkinter.CTkFont(weight="bold"))
            header_label.grid(row=0, column=col_idx, padx=10, pady=5, sticky="w")

        # Create Rows
        for row_idx, row_data in enumerate(data.get("rows", []), start=1):
            for col_idx, cell_text in enumerate(row_data):
                cell_label = customtkinter.CTkLabel(scrollable_frame, text=cell_text)
                cell_label.grid(row=row_idx, column=col_idx, padx=10, pady=5, sticky="w")

    def update_status(self, text):
        """Helper function to safely update the status bar from a thread."""
        if self.status_label:
            self.status_label.configure(text=text)

    def clear_current_tab(self):
        """Clears the content of the currently active tab's textbox."""
        active_tab = self.tab_view.get()
        target_tab = self.tab_view.tab(active_tab)
        if target_tab:
            for widget in target_tab.winfo_children():
                widget.destroy()

    def disable_buttons(self):
        """Disable all sidebar buttons to prevent multiple clicks."""
        for widget in self.sidebar_frame.winfo_children():
            if isinstance(widget, (customtkinter.CTkButton, customtkinter.CTkOptionMenu)):
                widget.configure(state="disabled")

    def enable_buttons(self):
        """Enable all sidebar buttons."""
        for widget in self.sidebar_frame.winfo_children():
            if isinstance(widget, (customtkinter.CTkButton, customtkinter.CTkOptionMenu)):
                widget.configure(state="normal")

    def switch_to_login_frame(self):
        """Hides the main app frame and shows the login frame."""
        self.main_frame.grid_remove()
        self.login_frame.grid(row=0, column=0, sticky="nsew")

    def switch_to_main_frame(self):
        """Hides the login frame and shows the main app frame."""
        self.login_frame.grid_remove()
        self.main_frame.grid(row=0, column=0, sticky="nsew")

    def log_out(self):
        """Logs the user out and returns to the login screen."""
        self.switch_to_login_frame()

if __name__ == "__main__":
    app = FPLApp()
    app.mainloop()