#!/bin/bash
# git hookをインストールするスクリプト
# 使い方: bash scripts/install_hooks.sh

REPO_DIR="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_DIR" ]; then
    echo "Error: gitリポジトリ内で実行してください"
    exit 1
fi

HOOK_DIR="$REPO_DIR/.git/hooks"

cat > "$HOOK_DIR/pre-push" << 'HOOK'
#!/bin/bash
# ABDS pre-push hook: gh-pagesブランチへのpush前にpre_deploy_check.pyを実行

remote="$1"

while read local_ref local_sha remote_ref remote_sha; do
    if [[ "$remote_ref" == "refs/heads/gh-pages" ]]; then
        echo ""
        echo "=========================================="
        echo "  gh-pages push detected"
        echo "  Running pre-deploy checks..."
        echo "=========================================="
        echo ""

        REPO_DIR="$(git rev-parse --show-toplevel)"
        CHECK_SCRIPT="$REPO_DIR/pre_deploy_check.py"

        if [ ! -f "$CHECK_SCRIPT" ]; then
            echo "WARNING: pre_deploy_check.py not found - skipping checks"
            exit 0
        fi

        python3 "$CHECK_SCRIPT" --quick
        result=$?

        if [ $result -ne 0 ]; then
            echo ""
            echo "=========================================="
            echo "  PUSH BLOCKED"
            echo "  pre_deploy_check.py failed."
            echo "  Fix the issues and try again."
            echo ""
            echo "  To skip: git push --no-verify"
            echo "=========================================="
            exit 1
        fi

        echo ""
        echo "  Pre-deploy checks passed. Pushing..."
        echo ""
    fi
done

exit 0
HOOK

chmod +x "$HOOK_DIR/pre-push"
echo "pre-push hook installed at $HOOK_DIR/pre-push"
