class Table:
    def __init__(self, title=""):
        self.title = title
        self.cols = []
        self.rows = []

    def add_column(self, col):
        self.cols.append(col)

    def add_row(self, *vals):
        self.rows.append(vals)

    def __str__(self):
        out = [self.title, " | ".join(self.cols)]
        for r in self.rows:
            out.append(" | ".join(str(x) for x in r))
        return "\n".join(out)
