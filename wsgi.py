from app import create_app

app = create_app()

if __name__ == '__main__':
    # Local development only
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.run(debug=True, port=5050)
