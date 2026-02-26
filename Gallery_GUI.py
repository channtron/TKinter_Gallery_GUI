import os
import time
import math
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pandas as pd
from PIL import Image, ImageTk
from collections import OrderedDict

# ---------------- CONFIG ----------------
THUMB_SIZE = (120, 120)
ROWS = 4
COLS = 5
IMAGES_PER_PAGE = ROWS * COLS
MAX_THUMB_CACHE = 300
# ----------------------------------------


class ThumbnailCache:
    def __init__(self, max_size):
        self.cache = OrderedDict()
        self.max_size = max_size

    def get(self, path):
        if path in self.cache:
            self.cache.move_to_end(path)
            return self.cache[path][0]
        return None

    def put(self, path, image):
        self.cache[path] = (image, time.time())
        self.cache.move_to_end(path)
        self._cleanup()

    def _cleanup(self):
        while len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

    def purge_unused(self, max_age_seconds=900):
        now = time.time()
        keys_to_remove = [
            k for k, (_, t) in self.cache.items()
            if now - t > max_age_seconds
        ]
        for k in keys_to_remove:
            del self.cache[k]


class ImageGallery(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Tkinter Image Gallery")
        self.geometry("1400x850")

        self.df = None
        self.filtered_df = None
        self.page = 0
        self.marked_page = 0
        self.selected_index = None

        self.thumb_cache = ThumbnailCache(MAX_THUMB_CACHE)

        self._load_dataframe()
        self._build_layout()
        self._apply_filters()

    # ---------- DATA ----------
    def _load_dataframe(self):
        self.dataset_path = filedialog.askopenfilename(
            title="Select dataframe",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")]
        )
        if not self.dataset_path:
            self.destroy()
            return

        self.dataset_name = os.path.basename(self.dataset_path)
        self.df = pd.read_csv(self.dataset_path)

        if not {"dir", "file"}.issubset(self.df.columns):
            messagebox.showerror("Error", "Dataframe must contain 'dir' and 'file'")
            self.destroy()
            return

        # Mark column
        if "__marked__" not in self.df.columns:
            self.df["__marked__"] = False

        # Column types
        self.numeric_keys = [
            c for c in self.df.columns
            if c not in ("dir", "file", "__marked__", "Unnamed: 0")
            and pd.api.types.is_numeric_dtype(self.df[c])
        ]

        self.category_keys = [
            c for c in self.df.columns
            if c not in ("dir", "file", "__marked__", "Unnamed: 0")
            and c not in self.numeric_keys
        ]

    # ---------- LAYOUT ----------
    def _build_layout(self):
        main = tk.PanedWindow(self, orient="horizontal")
        main.pack(fill="both", expand=True)

        self.filter_frame = tk.Frame(main, width=350)
        main.add(self.filter_frame)

        right = tk.Frame(main)
        main.add(right)

        self._build_filter_panel()
        self._build_gallery_tabs(right)
        self._build_info_panel(right)

    # ---------- FILTER PANEL ----------
    def _build_filter_panel(self):
        tk.Label(
            self.filter_frame, text=self.dataset_name,
            font=("TkDefaultFont", 10, "bold")
        ).pack(anchor="w", padx=10, pady=(10, 0))

        filters = tk.LabelFrame(self.filter_frame, text="Filters")
        filters.pack(fill="x", padx=10, pady=5)

        self.numeric_filters = {}
        self.category_filters = {}

        row = 0
        # Directory filter by name
        tk.Label(filters, text="Dir contains").grid(row=row, column=0, sticky="w")
        self.dir_search_var = tk.StringVar()
        tk.Entry(filters, textvariable=self.dir_search_var, width=25)\
            .grid(row=row, column=1, columnspan=2)
        row += 1
        # File name filter
        tk.Label(filters, text="File contains").grid(row=row, column=0, sticky="w")
        self.file_search_var = tk.StringVar()
        tk.Entry(filters, textvariable=self.file_search_var, width=25)\
            .grid(row=row, column=1, columnspan=2)
        row += 1

        for key in self.numeric_keys:
            tk.Label(filters, text=key).grid(row=row, column=0, sticky="w")

            mn = tk.DoubleVar(value=0.0)
            mx = tk.DoubleVar(value=1.0)

            tk.Scale(filters, from_=0, to=1, resolution=0.01,
                     orient="horizontal", variable=mn, length=120).grid(row=row, column=1)
            tk.Scale(filters, from_=0, to=1, resolution=0.01,
                     orient="horizontal", variable=mx, length=120).grid(row=row, column=2)

            self.numeric_filters[key] = (mn, mx)
            row += 1

        for key in self.category_keys:
            tk.Label(filters, text=key).grid(row=row, column=0, sticky="w")

            values = ["All"] + sorted(self.df[key].dropna().unique().tolist())
            var = tk.StringVar(value="All")
            ttk.Combobox(filters, values=values,
                         textvariable=var, state="readonly",
                         width=18).grid(row=row, column=1, columnspan=2)

            self.category_filters[key] = var
            row += 1

        self.hide_marked_var = tk.BooleanVar(value=False)
        tk.Checkbutton(filters, text="Hide marked files",
                       variable=self.hide_marked_var).grid(
            row=row, column=0, columnspan=3, sticky="w"
        )

        tk.Button(self.filter_frame, text="Apply filters",
                  command=self._apply_filters).pack(pady=5)

        tk.Button(self.filter_frame, text="⭐ Mark all filtered",
                  command=self._mark_all_filtered).pack(pady=(0, 5))
        
        tk.Button(self.filter_frame, text="💾 Save marks to CSV",
                  command=self._save_marks_to_csv).pack(pady=(0, 10))
        
        tk.Button(self.filter_frame, text="💾 Save as... (CSV)",
                  command=self._save_as_csv).pack(pady=(0, 10))

        self.count_label = tk.Label(self.filter_frame, text="")
        self.count_label.pack(anchor="w", padx=10)

    # ---------- GALLERY ----------
    def _build_gallery_tabs(self, parent):
        self.gallery_tabs = ttk.Notebook(parent)
        self.gallery_tabs.pack(fill="both", expand=True)

        self.gallery_frame = tk.Frame(self.gallery_tabs)
        self.marked_frame = tk.Frame(self.gallery_tabs)

        self.gallery_tabs.add(self.gallery_frame, text="Gallery")
        self.gallery_tabs.add(self.marked_frame, text="Marked")

        self._build_gallery(self.gallery_frame, marked=False)
        self._build_gallery(self.marked_frame, marked=True)

    def _build_gallery(self, parent, marked):
        thumb_frame = tk.Frame(parent)
        thumb_frame.pack()

        nav = tk.Frame(parent)
        nav.pack(pady=5)

        if marked:
            self.marked_thumb_frame = thumb_frame
            tk.Button(nav, text="<< Prev",
                      command=self._prev_marked_page).pack(side="left", padx=5)
            self.marked_page_label = tk.Label(nav, text="Page 1 / 1")
            self.marked_page_label.pack(side="left", padx=10)
            tk.Button(nav, text="Next >>",
                      command=self._next_marked_page).pack(side="left", padx=5)
            tk.Button(nav, text="Clear marked",
                      command=self._clear_marked).pack(side="left", padx=10)
            tk.Button(nav, text="Export marked (.txt)",
                      command=self._export_marked_txt).pack(side="left", padx=10)
        else:
            self.thumb_frame = thumb_frame
            tk.Button(nav, text="<< Prev",
                      command=self._prev_page).pack(side="left", padx=5)
            self.page_label = tk.Label(nav, text="Page 1 / 1")
            self.page_label.pack(side="left", padx=10)
            tk.Button(nav, text="Next >>",
                      command=self._next_page).pack(side="left", padx=5)

    # ---------- INFO PANEL ----------
    def _build_info_panel(self, parent):
        self.info_tabs = ttk.Notebook(parent)
        self.info_tabs.pack(fill="x", padx=10, pady=5)

        self.table_tab = tk.Frame(self.info_tabs)
        self.info_tabs.add(self.table_tab, text="Details")
        self.info_tabs.select(self.table_tab)

        self.dir_file_lbl = tk.Label(self.table_tab, justify="left")
        self.dir_file_lbl.pack(anchor="w", pady=5)

        content = tk.Frame(self.table_tab)
        content.pack(fill="x")

        self.table = ttk.Treeview(content, show="headings", height=2)
        self.table.pack(side="left", fill="x", expand=True)

        btns = tk.Frame(content)
        btns.pack(side="right", padx=10)

        self.open_btn = tk.Button(btns, text="Open full size",
                                  state="disabled", command=self._open_full_image)
        self.open_btn.pack(fill="x", pady=2)

        self.mark_btn = tk.Button(btns, text="Mark / Unmark",
                                  state="disabled", command=self._toggle_mark)
        self.mark_btn.pack(fill="x", pady=2)
        self.same_name_var = tk.BooleanVar(value=False)
        tk.Checkbutton(btns, text="Show same filename",
                       variable=self.same_name_var, command=self._toggle_same_name_filter)\
                        .pack(fill="x", pady=4)

    # ---------- FILTERING ----------
    def _apply_filters(self, reset_page=True):
        df = self.df.copy()

        for k, (mn, mx) in self.numeric_filters.items():
            df = df[(df[k] >= mn.get()) & (df[k] <= mx.get())]

        for k, var in self.category_filters.items():
            if var.get() != "All":
                df = df[df[k] == var.get()]

        dir_q = self.dir_search_var.get().strip().lower()
        if dir_q:
            df = df[df["dir"].str.lower().str.contains(dir_q, case=False)]

        file_q = self.file_search_var.get().strip().lower()
        if file_q:
            df = df[df["file"].str.lower().str.contains(file_q, case=False)]

        if self.hide_marked_var.get():
            df = df[df["__marked__"] == False]

        self.filtered_df = df.reset_index()
        max_page = max(0, math.ceil(len(self.filtered_df) / IMAGES_PER_PAGE) - 1)
        self.page = min(self.page, max_page)
        if reset_page:
            self.page = 0
        self.selected_index = None
        self._render_gallery()
        self._render_marked()
        self._update_counts()
        self._update_info()

    # ---------- RENDER ----------
    def _render_gallery(self):
        self._render_page(self.thumb_frame, self.filtered_df, self.page)
        self._update_page_label()

    def _render_marked(self):
        marked_df = self.df[self.df["__marked__"]].reset_index()
        self._render_page(self.marked_thumb_frame, marked_df, self.marked_page)
        self._update_marked_page_label()

    def _render_page(self, frame, df, page):
        self.thumb_cache.purge_unused()
        for w in frame.winfo_children():
            w.destroy()

        start = page * IMAGES_PER_PAGE
        page_df = df.iloc[start:start + IMAGES_PER_PAGE]

        for i, row in page_df.iterrows():
            r, c = divmod(i - start, COLS)
            path = os.path.join(row["dir"], row["file"])

            thumb = self.thumb_cache.get(path)
            if thumb is None:
                try:
                    img = Image.open(path)
                    img.thumbnail(THUMB_SIZE)
                    thumb = ImageTk.PhotoImage(img)
                    self.thumb_cache.put(path, thumb)
                except Exception:
                    continue

            lbl = tk.Label(frame, image=thumb, bd=2)
            lbl.image = thumb
            lbl.grid(row=r, column=c, padx=5, pady=5)
            lbl.bind("<Button-1>", lambda e, idx=row["index"]: self._select_row(idx))

    # --------- UPDATE LABELS ----------
    def _update_page_label(self):
        total_pages = max(1, math.ceil(len(self.filtered_df) / IMAGES_PER_PAGE))
        self.page_label.config(
            text=f"Page {self.page + 1} / {total_pages}"
        )

    def _update_marked_page_label(self):
        marked_count = int(self.df["__marked__"].sum())
        total_pages = max(1, math.ceil(marked_count / IMAGES_PER_PAGE))
        self.marked_page_label.config(
            text=f"Page {self.marked_page + 1} / {total_pages}"
        )

    # ---------- INFO ----------
    def _select_row(self, idx):
        self.selected_index = idx
        self._update_info()

    def _update_info(self):
        self.table.delete(*self.table.get_children())
        self.table["columns"] = ()
        self.dir_file_lbl.config(text="")
        self.open_btn.config(state="disabled")
        self.mark_btn.config(state="disabled")

        if self.selected_index is None:
            return

        r = self.df.loc[self.selected_index]
        path = os.path.join(r["dir"], r["file"])

        self.open_btn.config(state="normal")
        self.mark_btn.config(state="normal")
        is_marked = bool(r["__marked__"])
        self.mark_btn.config(text="Unmark" if is_marked else "Mark")

        self.dir_file_lbl.config(text=f"Dir: {r['dir']}\nFile: {r['file']}")

        self.table["columns"] = self.numeric_keys + self.category_keys
        for k in self.table["columns"]:
            self.table.heading(k, text=k)
            self.table.column(k, width=100, anchor="center")

        self.table.insert("", "end", values=[r[k] for k in self.table["columns"]])

    def _toggle_same_name_filter(self):
        if not self.same_name_var.get() or self.selected_index is None:
            self._apply_filters()
            return

        fname = self.df.at[self.selected_index, "file"]
        self.filtered_df = (
            self.df[self.df["file"] == fname]
            .reset_index()
        )
        self.page = 0
        self._render_gallery()

    # ---------- MARKING ----------
    def _toggle_mark(self):
        if self.selected_index is None:
            return

        current = self.df.at[self.selected_index, "__marked__"]
        self.df.at[self.selected_index, "__marked__"] = not current
        self._apply_filters(reset_page=False)

    def _mark_all_filtered(self):
        self.df.loc[self.filtered_df["index"], "__marked__"] = True
        self._apply_filters(reset_page=False)

    def _clear_marked(self):
        self.df["__marked__"] = False
        self._apply_filters(reset_page=False)

    def _save_marks_to_csv(self):
        if not self.dataset_path:
            messagebox.showerror("Error", "No dataset path available.")
            return

        marked_count = int(self.df["__marked__"].sum())

        confirm = messagebox.askyesno(
            "Save marks",
            f"This will overwrite the CSV file:\n\n"
            f"{self.dataset_path}\n\n"
            f"Marked files: {marked_count}\n\n"
            f"Do you want to continue?"
        )

        if not confirm:
            return

        try:
            self.df.to_csv(self.dataset_path, index=False)
            messagebox.showinfo(
                "Success",
                f"Marks saved successfully.\n\n"
                f"Marked files: {marked_count}"
            )
        except Exception as e:
            messagebox.showerror(
                "Error",
                f"Failed to save CSV:\n\n{str(e)}"
            )

    def _save_as_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")]
        )
        if not path:
            return

        try:
            self.df.to_csv(path, index=False)
            messagebox.showinfo(
                "Saved",
                f"Dataset saved successfully:\n{path}"
            )
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _export_marked_txt(self):
        marked_df = self.df[self.df["__marked__"]]

        if marked_df.empty:
            messagebox.showinfo("Export", "No marked files to export.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text file", "*.txt")]
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                for _, r in marked_df.iterrows():
                    f.write(os.path.join(r["dir"], r["file"]) + "\n")

            messagebox.showinfo(
                "Export complete",
                f"Exported {len(marked_df)} file paths."
            )
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ---------- VIEW ----------
    def _open_full_image(self):
        if self.selected_index is None:
            return
        r = self.df.loc[self.selected_index]
        path = os.path.join(r["dir"], r["file"])
        try:
            img = Image.open(path)
        except Exception:
            return

        win = tk.Toplevel(self)
        win.title(os.path.basename(path))
        tk_img = ImageTk.PhotoImage(img)
        lbl = tk.Label(win, image=tk_img)
        lbl.image = tk_img
        lbl.pack()

    # ---------- PAGINATION ----------
    def _next_page(self):
        max_page = max(0, math.ceil(len(self.filtered_df) / IMAGES_PER_PAGE) - 1)
        if self.page < max_page:
            self.page += 1
            self._render_gallery()

    def _prev_page(self):
        if self.page > 0:
            self.page -= 1
            self._render_gallery()

    def _next_marked_page(self):
        marked_count = self.df["__marked__"].sum()
        if (self.marked_page + 1) * IMAGES_PER_PAGE < marked_count:
            self.marked_page += 1
            self._render_marked()

    def _prev_marked_page(self):
        if self.marked_page > 0:
            self.marked_page -= 1
            self._render_marked()

    def _update_counts(self):
        self.count_label.config(
            text=f"Filtered: {len(self.filtered_df)} / {len(self.df)}"
        )


if __name__ == "__main__":
    ImageGallery().mainloop()