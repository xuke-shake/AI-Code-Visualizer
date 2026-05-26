from fastapi import status


class AppException(Exception):
    def __init__(self, message: str, code: int = 40000, status_code: int = status.HTTP_400_BAD_REQUEST):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class NotFoundException(AppException):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message, code=40400, status_code=status.HTTP_404_NOT_FOUND)


class UnauthorizedException(AppException):
    def __init__(self, message: str = "未登录或Token无效"):
        super().__init__(message, code=40100, status_code=status.HTTP_401_UNAUTHORIZED)


class ForbiddenException(AppException):
    def __init__(self, message: str = "无权限执行该操作"):
        super().__init__(message, code=40300, status_code=status.HTTP_403_FORBIDDEN)


class ConflictException(AppException):
    def __init__(self, message: str = "资源冲突"):
        super().__init__(message, code=40900, status_code=status.HTTP_409_CONFLICT)
