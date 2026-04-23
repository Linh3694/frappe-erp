### Erp

An app for WSHN’s internal applications.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app erp
```

### patch lên cây Frappe (tùy chọn, Socket.IO + JWT / SPA)

Một số tính năng cần sửa file trong `apps/frappe` (không nằm trong repo `erp` khi bạn chỉ push app). Xem hướng dẫn, nâng cấp Frappe, và tệp patch trong [patches/core/README.md](./patches/core/README.md). Sau khi cài bench:

```bash
cd apps/erp && ./scripts/apply-frappe-core-patches.sh
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/erp
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
