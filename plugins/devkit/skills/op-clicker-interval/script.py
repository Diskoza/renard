print(set_field('OP Auto Clicker', 'secs', ARGS['secs'])); print(set_field('OP Auto Clicker', 'milliseconds', ARGS.get('ms', 0)))
f = fields('OP Auto Clicker'); print('сейчас:', f['secs'], 'с', f['milliseconds'], 'мс')
